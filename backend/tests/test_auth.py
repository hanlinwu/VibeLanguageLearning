import os
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.main import app


def test_register_login_me_flow() -> None:
    with TestClient(app) as client:
        payload = {
            'email': f"test-{uuid.uuid4().hex[:8]}@example.com",
            'password': 'secret123',
            'display_name': 'Tester',
        }
        reg = client.post('/auth/register', json=payload)
        assert reg.status_code == 201

        login = client.post('/auth/login', json={'email': payload['email'], 'password': payload['password']})
        assert login.status_code == 200
        token = login.json()['access_token']

        me = client.get('/auth/me', headers={'Authorization': f'Bearer {token}'})
        assert me.status_code == 200
        body = me.json()
        assert body['email'] == payload['email']
        assert body['display_name'] == payload['display_name']
