import os
import json
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.llm_client import llm_client
from app.main import app
from app.models import ChatConversation, User
from app.db import SessionLocal
from app.services.query import stream_answer_question


def _register_login_and_seed(client: TestClient) -> str:
    email = f"query-{uuid.uuid4().hex[:8]}@example.com"
    payload = {'email': email, 'password': 'secret123', 'display_name': 'Tester'}
    reg = client.post('/auth/register', json=payload)
    assert reg.status_code == 201

    login = client.post('/auth/login', json={'email': payload['email'], 'password': payload['password']})
    assert login.status_code == 200
    token = login.json()['access_token']

    files = {'file': ('grammar.md', b'Le verbe etre au present: je suis, tu es, il est.', 'text/markdown')}
    upload = client.post('/knowledge/upload', files=files, headers={'Authorization': f'Bearer {token}'})
    assert upload.status_code == 200
    return token


def test_query_returns_answer_with_citations_and_trace_id() -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        response = client.post('/query', json={'question': 'Comment conjuguer etre?'}, headers={'Authorization': f'Bearer {token}'})

        assert response.status_code == 200
        body = response.json()
        assert body['answer']
        assert 'trace_id' in body and len(body['trace_id']) > 10
        assert isinstance(body['conversation_id'], int)
        assert isinstance(body['citations'], list)
        assert len(body['citations']) >= 1
        first = body['citations'][0]
        assert isinstance(first.get('chunk_id'), int)
        assert isinstance(first.get('document_id'), int)
        assert first.get('document_filename')
        assert isinstance(first.get('knowledge_base_id'), int)
        assert first.get('knowledge_base_name')
        assert isinstance(first.get('relevance_score'), float)


def test_query_rerank_keeps_only_relevant_citations(monkeypatch) -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        files = {'file': ('noise.md', b'My favorite pizza topping is olive.', 'text/markdown')}
        upload = client.post('/knowledge/upload', files=files, headers=headers)
        assert upload.status_code == 200

        def fake_rerank_texts(query: str, documents: list[str], top_k: int):
            results: list[dict] = []
            for idx, doc in enumerate(documents):
                score = 0.96 if 'verbe etre' in doc.lower() else 0.08
                results.append({'index': idx, 'score': score})
            return results

        monkeypatch.setattr(llm_client, 'rerank_texts', fake_rerank_texts, raising=False)

        response = client.post('/query', json={'question': 'Comment conjuguer etre?'}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body['citations']) == 1
        assert body['citations'][0]['document_filename'] == 'grammar.md'


def test_query_returns_empty_citations_when_rerank_returns_no_results(monkeypatch) -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        monkeypatch.setattr(llm_client, 'rerank_texts', lambda query, documents, top_k: [], raising=False)

        response = client.post('/query', json={'question': '请解释这个动词的现在时变位'}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body['citations'] == []


def test_query_sends_vector_topk_candidates_to_rerank(monkeypatch) -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        files = {'file': ('noise.md', b'Completely unrelated text.', 'text/markdown')}
        upload = client.post('/knowledge/upload', files=files, headers=headers)
        assert upload.status_code == 200

        captured: dict = {}

        def capture_rerank(query: str, documents: list[str], top_k: int):
            captured['query'] = query
            captured['documents_count'] = len(documents)
            captured['top_k'] = top_k
            return [{'index': 0, 'score': 0.92}]

        monkeypatch.setattr(llm_client, 'rerank_texts', capture_rerank, raising=False)

        response = client.post('/query', json={'question': 'Comment conjuguer etre?'}, headers=headers)
        assert response.status_code == 200
        assert captured['documents_count'] >= 2
        assert captured['top_k'] == captured['documents_count']


def test_query_can_retrieve_from_public_knowledge_base() -> None:
    with TestClient(app) as client:
        admin_token = _register_login_and_seed(client)
        me_admin = client.get('/auth/me', headers={'Authorization': f'Bearer {admin_token}'})
        assert me_admin.status_code == 200
        admin_user_id = me_admin.json()['id']
        admin_email = me_admin.json()['email']

        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.id == admin_user_id).first()
            assert admin is not None
            admin.is_admin = True
            db.add(admin)
            db.commit()
        finally:
            db.close()

        admin_headers = {'Authorization': f'Bearer {admin_token}'}
        create_public = client.post('/knowledge/bases', json={'name': '公共法语库', 'scope': 'public'}, headers=admin_headers)
        assert create_public.status_code == 200
        public_base_id = create_public.json()['id']
        files = {'file': ('public-etre.md', b'etre present: je suis, tu es, il est.', 'text/markdown')}
        upload = client.post(f'/knowledge/upload?knowledge_base_id={public_base_id}', files=files, headers=admin_headers)
        assert upload.status_code == 200

        # another user without private knowledge should still retrieve public citation
        email = f"query-pub-{uuid.uuid4().hex[:8]}@example.com"
        reg = client.post('/auth/register', json={'email': email, 'password': 'secret123', 'display_name': 'Tester2'})
        assert reg.status_code == 201
        login = client.post('/auth/login', json={'email': email, 'password': 'secret123'})
        assert login.status_code == 200
        token2 = login.json()['access_token']
        headers2 = {'Authorization': f'Bearer {token2}'}

        response = client.post('/query', json={'question': 'Comment conjuguer etre?'}, headers=headers2)
        assert response.status_code == 200
        body = response.json()
        assert any(item.get('document_filename') == 'public-etre.md' for item in body['citations'])


def test_query_stream_returns_sse_chunks_and_done_event() -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        chunks: list[str] = []
        done = False

        with client.stream(
            'POST',
            '/query/stream',
            json={'question': 'Comment utiliser etre en contexte?'},
            headers={'Authorization': f'Bearer {token}'},
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line or not line.startswith('data: '):
                    continue
                payload = json.loads(line[len('data: ') :])
                if payload.get('type') == 'chunk':
                    chunks.append(payload.get('content', ''))
                if payload.get('type') == 'done':
                    done = True
                    assert isinstance(payload.get('conversation_id'), int)

        assert ''.join(chunks) == 'TEST_STREAM_ANSWER'
        assert done is True


def test_conversation_endpoints_and_context_scoping() -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        first = client.post('/query', json={'question': 'Premier sujet'}, headers=headers)
        assert first.status_code == 200
        conversation_id = first.json()['conversation_id']

        second = client.post(
            '/query',
            json={'question': 'Suivi du premier sujet', 'conversation_id': conversation_id},
            headers=headers,
        )
        assert second.status_code == 200
        assert second.json()['conversation_id'] == conversation_id

        list_resp = client.get('/interactions/conversations', headers=headers)
        assert list_resp.status_code == 200
        conversations = list_resp.json()
        assert any(item['id'] == conversation_id for item in conversations)

        messages_resp = client.get(f'/interactions/conversations/{conversation_id}/messages', headers=headers)
        assert messages_resp.status_code == 200
        messages = messages_resp.json()
        assert len(messages) >= 2
        assert all(item['conversation_id'] == conversation_id for item in messages)


def test_query_stream_persists_partial_answer_when_upstream_interrupts(monkeypatch) -> None:
    def flaky_stream_chat_messages(messages: list[dict[str, str]]):
        yield 'PARTIAL_'
        raise RuntimeError('upstream interrupted')

    monkeypatch.setattr(llm_client, 'stream_chat_messages', flaky_stream_chat_messages)

    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        chunks: list[str] = []
        done = False
        conversation_id = None
        with client.stream(
            'POST',
            '/query/stream',
            json={'question': 'Test interruption'},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line or not line.startswith('data: '):
                    continue
                payload = json.loads(line[len('data: ') :])
                if payload.get('type') == 'start':
                    conversation_id = payload.get('conversation_id')
                if payload.get('type') == 'chunk':
                    chunks.append(payload.get('content', ''))
                if payload.get('type') == 'done':
                    done = True

        assert ''.join(chunks) == 'PARTIAL_'
        assert done is True
        assert isinstance(conversation_id, int)

        messages_resp = client.get(f'/interactions/conversations/{conversation_id}/messages', headers=headers)
        assert messages_resp.status_code == 200
        messages = messages_resp.json()
        assert len(messages) >= 1
        assert messages[-1]['answer'].startswith('PARTIAL_')


def test_query_stream_persists_partial_answer_when_client_disconnects() -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        conversation_id = None
        with client.stream(
            'POST',
            '/query/stream',
            json={'question': 'Client abort test'},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line or not line.startswith('data: '):
                    continue
                payload = json.loads(line[len('data: ') :])
                if payload.get('type') == 'start':
                    conversation_id = payload.get('conversation_id')
                if payload.get('type') == 'chunk':
                    # Simulate browser stop button: stop reading and close stream immediately.
                    break

        assert isinstance(conversation_id, int)

        messages_resp = client.get(f'/interactions/conversations/{conversation_id}/messages', headers=headers)
        assert messages_resp.status_code == 200
        messages = messages_resp.json()
        assert len(messages) >= 1
        assert messages[-1]['question'] == 'Client abort test'
        assert messages[-1]['answer'].startswith('TEST_')


def test_query_stream_persists_record_when_stopped_before_first_chunk() -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}
        me = client.get('/auth/me', headers=headers)
        assert me.status_code == 200
        user_id = me.json()['id']

        db = SessionLocal()
        try:
            stream = stream_answer_question(db, user_id, 'Stop before first chunk test')
            first_event = next(stream)
            payload = json.loads(first_event[len('data: ') :].strip())
            conversation_id = payload.get('conversation_id')
            stream.close()

            messages_resp = client.get(f'/interactions/conversations/{conversation_id}/messages', headers=headers)
            assert messages_resp.status_code == 200
            messages = messages_resp.json()
            assert len(messages) >= 1
            assert messages[-1]['question'] == 'Stop before first chunk test'
        finally:
            db.close()


def test_soft_delete_conversation_marks_deleted_without_physical_delete() -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        first = client.post('/query', json={'question': 'Sujet a supprimer'}, headers=headers)
        assert first.status_code == 200
        conversation_id = first.json()['conversation_id']

        delete_resp = client.delete(f'/interactions/conversations/{conversation_id}', headers=headers)
        assert delete_resp.status_code == 200
        assert delete_resp.json()['deleted'] is True

        list_resp = client.get('/interactions/conversations', headers=headers)
        assert list_resp.status_code == 200
        ids = [item['id'] for item in list_resp.json()]
        assert conversation_id not in ids

        messages_resp = client.get(f'/interactions/conversations/{conversation_id}/messages', headers=headers)
        assert messages_resp.status_code == 200
        assert messages_resp.json() == []

        db = SessionLocal()
        try:
            conv = db.query(ChatConversation).filter(ChatConversation.id == conversation_id).first()
            assert conv is not None
            assert conv.deleted_at is not None
        finally:
            db.close()


def test_rename_conversation_updates_title() -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        first = client.post('/query', json={'question': 'Sujet renommage'}, headers=headers)
        assert first.status_code == 200
        conversation_id = first.json()['conversation_id']

        rename_resp = client.patch(
            f'/interactions/conversations/{conversation_id}',
            json={'title': '新会话标题'},
            headers=headers,
        )
        assert rename_resp.status_code == 200
        body = rename_resp.json()
        assert body['updated'] is True
        assert body['title'] == '新会话标题'

        list_resp = client.get('/interactions/conversations', headers=headers)
        assert list_resp.status_code == 200
        target = next((item for item in list_resp.json() if item['id'] == conversation_id), None)
        assert target is not None
        assert target['title'] == '新会话标题'


def test_memory_stream_tracks_create_update_and_delete_history() -> None:
    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        first = client.post(
            '/query',
            json={'question': '我喜欢先做语法练习，尤其是动词变位，总是搞不清'},
            headers=headers,
        )
        assert first.status_code == 200

        stream_resp = client.get('/memory/stream', headers=headers)
        assert stream_resp.status_code == 200
        stream_body = stream_resp.json()
        assert len(stream_body['items']) >= 1
        assert len(stream_body['changes']) >= 1
        assert any(item['category'] in ('preference', 'grammar') for item in stream_body['items'])
        assert any(change['action'] == 'create' for change in stream_body['changes'])

        second = client.post(
            '/query',
            json={'question': '我现在更喜欢先听力后口语训练，变位还是不熟'},
            headers=headers,
        )
        assert second.status_code == 200

        stream_resp2 = client.get('/memory/stream', headers=headers)
        assert stream_resp2.status_code == 200
        stream_body2 = stream_resp2.json()
        assert any(change['action'] == 'update' for change in stream_body2['changes'])

        target_item = stream_body2['items'][0]
        delete_resp = client.delete(f"/memory/items/{target_item['id']}", headers=headers)
        assert delete_resp.status_code == 200
        assert delete_resp.json()['deleted'] is True

        stream_resp3 = client.get('/memory/stream', headers=headers)
        assert stream_resp3.status_code == 200
        stream_body3 = stream_resp3.json()
        assert all(item['id'] != target_item['id'] for item in stream_body3['items'])
        assert any(
            change['action'] == 'delete' and change['item_id'] == target_item['id']
            for change in stream_body3['changes']
        )


def test_memory_extraction_uses_llm_structured_output(monkeypatch) -> None:
    def fake_chat(system_prompt: str, user_prompt: str) -> str:
        if '长期记忆提炼器' in system_prompt:
            return json.dumps(
                [
                    {
                        'category': 'preference',
                        'memory_key': 'preference:study_mode',
                        'content': '用户偏好先语法后口语练习',
                        'importance': 0.91,
                        'reason': 'explicit-preference',
                    },
                    {
                        'category': 'grammar',
                        'memory_key': 'grammar:动词变位',
                        'content': '动词变位仍是薄弱点',
                        'importance': 0.95,
                        'reason': 'mastery-gap',
                    },
                ],
                ensure_ascii=False,
            )
        return '常规回答'

    monkeypatch.setattr(llm_client, 'chat', fake_chat)

    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        resp = client.post('/query', json={'question': '我更喜欢先语法后口语，变位一直不会'}, headers=headers)
        assert resp.status_code == 200

        stream_resp = client.get('/memory/stream', headers=headers)
        assert stream_resp.status_code == 200
        body = stream_resp.json()

        keys = [item['memory_key'] for item in body['items']]
        assert 'preference:study_mode' in keys
        assert 'grammar:动词变位' in keys
        assert any(change['action'] == 'create' for change in body['changes'])


def test_explicit_save_to_memory_stream_must_persist(monkeypatch) -> None:
    def fake_chat(system_prompt: str, user_prompt: str) -> str:
        if '长期记忆提炼器' in system_prompt:
            return '[]'
        if '强制记忆总结器' in system_prompt:
            return json.dumps(
                {
                    'category': 'manual',
                    'memory_key': 'manual:custom',
                    'content': '用户要求记住：未来两周重点突破动词变位',
                    'importance': 0.97,
                    'reason': 'explicit-save-request',
                },
                ensure_ascii=False,
            )
        return '常规回答'

    monkeypatch.setattr(llm_client, 'chat', fake_chat)

    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        resp = client.post(
            '/query',
            json={'question': '请把这条保存到记忆流：未来两周重点突破动词变位'},
            headers=headers,
        )
        assert resp.status_code == 200

        stream_resp = client.get('/memory/stream', headers=headers)
        assert stream_resp.status_code == 200
        body = stream_resp.json()
        assert any(item['category'] == 'manual' for item in body['items'])
        assert any('未来两周重点突破动词变位' in item['content'] for item in body['items'])


def test_new_conversation_injects_memory_stream_into_system_prompt(monkeypatch) -> None:
    captured_system_prompts: list[str] = []

    def fake_chat(system_prompt: str, user_prompt: str) -> str:
        if '长期记忆提炼器' in system_prompt:
            return '[]'
        if '强制记忆总结器' in system_prompt:
            return json.dumps(
                {
                    'category': 'manual',
                    'memory_key': 'manual:focus',
                    'content': '长期目标：优先提升法语动词变位正确率',
                    'importance': 0.96,
                    'reason': 'explicit-save-request',
                },
                ensure_ascii=False,
            )
        return '常规回答'

    def fake_chat_messages(messages: list[dict[str, str]]) -> str:
        system_text = '\n'.join(msg.get('content', '') for msg in messages if msg.get('role') == 'system')
        captured_system_prompts.append(system_text)
        return '常规回答'

    monkeypatch.setattr(llm_client, 'chat', fake_chat)
    monkeypatch.setattr(llm_client, 'chat_messages', fake_chat_messages)

    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        first = client.post(
            '/query',
            json={'question': '保存到记忆流：长期目标是优先提升法语动词变位正确率'},
            headers=headers,
        )
        assert first.status_code == 200

        second = client.post(
            '/query',
            json={'question': '我们开始一个新话题，给我学习建议'},
            headers=headers,
        )
        assert second.status_code == 200

        assert len(captured_system_prompts) >= 2
        assert '长期记忆' in captured_system_prompts[-1]
        assert '优先提升法语动词变位正确率' in captured_system_prompts[-1]


def test_disable_memory_stream_skips_memory_injection_and_persistence(monkeypatch) -> None:
    captured_system_prompts: list[str] = []

    def fake_chat(system_prompt: str, user_prompt: str) -> str:
        if '长期记忆提炼器' in system_prompt:
            return json.dumps(
                [
                    {
                        'category': 'manual',
                        'memory_key': 'manual:focus',
                        'content': '应当不会落库',
                        'importance': 0.9,
                        'reason': 'explicit-save-request',
                    }
                ],
                ensure_ascii=False,
            )
        if '强制记忆总结器' in system_prompt:
            return json.dumps(
                {
                    'category': 'manual',
                    'memory_key': 'manual:forced',
                    'content': '应当不会落库',
                    'importance': 0.9,
                    'reason': 'explicit-save-request',
                },
                ensure_ascii=False,
            )
        return '常规回答'

    def fake_chat_messages(messages: list[dict[str, str]]) -> str:
        system_text = '\n'.join(msg.get('content', '') for msg in messages if msg.get('role') == 'system')
        captured_system_prompts.append(system_text)
        return '常规回答'

    monkeypatch.setattr(llm_client, 'chat', fake_chat)
    monkeypatch.setattr(llm_client, 'chat_messages', fake_chat_messages)

    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        first = client.post(
            '/query',
            json={'question': '保存到记忆流：这条不应该入库', 'use_memory_stream': False},
            headers=headers,
        )
        assert first.status_code == 200

        second = client.post(
            '/query',
            json={'question': '新的对话继续', 'use_memory_stream': False},
            headers=headers,
        )
        assert second.status_code == 200

        stream_resp = client.get('/memory/stream', headers=headers)
        assert stream_resp.status_code == 200
        stream_body = stream_resp.json()
        assert stream_body['items'] == []
        assert stream_body['changes'] == []

        assert len(captured_system_prompts) >= 2
        assert '长期记忆（跨对话）' not in captured_system_prompts[-1]


def test_enable_memory_stream_mid_conversation_takes_effect(monkeypatch) -> None:
    captured_system_prompts: list[str] = []

    def fake_chat(system_prompt: str, user_prompt: str) -> str:
        if '长期记忆提炼器' in system_prompt:
            return '[]'
        if '强制记忆总结器' in system_prompt:
            return json.dumps(
                {
                    'category': 'manual',
                    'memory_key': 'manual:focus',
                    'content': '记住：优先复习动词变位',
                    'importance': 0.95,
                    'reason': 'explicit-save-request',
                },
                ensure_ascii=False,
            )
        return '常规回答'

    def fake_chat_messages(messages: list[dict[str, str]]) -> str:
        system_text = '\n'.join(msg.get('content', '') for msg in messages if msg.get('role') == 'system')
        captured_system_prompts.append(system_text)
        return '常规回答'

    monkeypatch.setattr(llm_client, 'chat', fake_chat)
    monkeypatch.setattr(llm_client, 'chat_messages', fake_chat_messages)

    with TestClient(app) as client:
        token = _register_login_and_seed(client)
        headers = {'Authorization': f'Bearer {token}'}

        # 先建立一条记忆（新会话，开启记忆流）
        first = client.post(
            '/query',
            json={'question': '保存到记忆流：优先复习动词变位', 'use_memory_stream': True},
            headers=headers,
        )
        assert first.status_code == 200
        conversation_id = first.json()['conversation_id']

        # 同一会话里先关闭再开启，开启后应立即注入记忆流
        second = client.post(
            '/query',
            json={'question': '先不启用记忆', 'conversation_id': conversation_id, 'use_memory_stream': False},
            headers=headers,
        )
        assert second.status_code == 200

        third = client.post(
            '/query',
            json={'question': '现在开启记忆流继续聊', 'conversation_id': conversation_id, 'use_memory_stream': True},
            headers=headers,
        )
        assert third.status_code == 200

        assert len(captured_system_prompts) >= 3
        assert '长期记忆（跨对话）' in captured_system_prompts[-1]
        assert '优先复习动词变位' in captured_system_prompts[-1]
