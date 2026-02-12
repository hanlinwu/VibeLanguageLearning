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


def test_upload_markdown_and_list_docs() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        files = {'file': ('french.md', b'# Bonjour\\nLe present de etre.', 'text/markdown')}

        upload = client.post('/knowledge/upload', files=files, headers={'Authorization': f'Bearer {token}'})
        assert upload.status_code == 200
        body = upload.json()
        assert body['document_id'] > 0
        assert body['chunks'] >= 1

        docs = client.get('/knowledge/docs', headers={'Authorization': f'Bearer {token}'})
        assert docs.status_code == 200
        assert any(item['filename'] == 'french.md' for item in docs.json())
