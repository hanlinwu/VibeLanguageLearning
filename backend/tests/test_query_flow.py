import os
import json
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.llm_client import llm_client
from app.main import app
from app.models import ChatConversation
from app.db import SessionLocal


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
    def flaky_stream_chat(system_prompt: str, user_prompt: str):
        yield 'PARTIAL_'
        raise RuntimeError('upstream interrupted')

    monkeypatch.setattr(llm_client, 'stream_chat', flaky_stream_chat)

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
