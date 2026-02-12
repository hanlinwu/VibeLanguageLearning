import os
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.main import app


def _register_and_login(client: TestClient) -> str:
    email = f"knowledge-{uuid.uuid4().hex[:8]}@example.com"
    payload = {'email': email, 'password': 'secret123', 'display_name': 'Tester'}
    reg = client.post('/auth/register', json=payload)
    assert reg.status_code == 201

    login = client.post('/auth/login', json={'email': payload['email'], 'password': payload['password']})
    assert login.status_code == 200
    return login.json()['access_token']


def test_upload_markdown_and_manage_multiple_bases() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        create_base = client.post('/knowledge/bases', json={'name': '语法库'}, headers=headers)
        assert create_base.status_code == 200
        base_id = create_base.json()['id']

        toggle_base = client.patch(f'/knowledge/bases/{base_id}', json={'is_enabled': False}, headers=headers)
        assert toggle_base.status_code == 200
        assert toggle_base.json()['is_enabled'] is False

        enable_base = client.patch(f'/knowledge/bases/{base_id}', json={'is_enabled': True}, headers=headers)
        assert enable_base.status_code == 200
        assert enable_base.json()['is_enabled'] is True

        files = {'file': ('french.md', b'# Bonjour\\nLe present de etre.', 'text/markdown')}

        upload = client.post(f'/knowledge/upload?knowledge_base_id={base_id}', files=files, headers=headers)
        assert upload.status_code == 200
        body = upload.json()
        assert body['document_id'] > 0
        assert body['knowledge_base_id'] == base_id
        assert body['status'] in {'queued', 'slicing', 'embedding', 'completed'}

        docs = client.get(f'/knowledge/docs?knowledge_base_id={base_id}', headers=headers)
        assert docs.status_code == 200
        payload = docs.json()
        assert any(item['filename'] == 'french.md' for item in payload)
        item = next(item for item in payload if item['filename'] == 'french.md')
        assert item['status'] in {'queued', 'slicing', 'embedding', 'completed'}
        assert 'chunk_count' in item
        assert 'processed_chunks' in item
        assert 'total_chunks' in item

        bases = client.get('/knowledge/bases', headers=headers)
        assert bases.status_code == 200
        assert any(item['id'] == base_id for item in bases.json())
