import os
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.main import app


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
        assert isinstance(body['citations'], list)
        assert len(body['citations']) >= 1
