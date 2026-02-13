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
        assert isinstance(body.get('avatar_url'), str)
        assert body['avatar_url']


def test_update_me_target_language() -> None:
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
        headers = {'Authorization': f'Bearer {token}'}

        upd = client.patch('/auth/me', json={'target_language': '日语'}, headers=headers)
        assert upd.status_code == 200
        assert upd.json()['target_language'] == '日语'

        me = client.get('/auth/me', headers=headers)
        assert me.status_code == 200
        assert me.json()['target_language'] == '日语'


def test_regenerate_avatar() -> None:
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
        headers = {'Authorization': f'Bearer {token}'}

        me = client.get('/auth/me', headers=headers)
        assert me.status_code == 200
        old_avatar = me.json().get('avatar_url')
        assert old_avatar

        regen = client.post('/auth/me/avatar/regenerate', headers=headers)
        assert regen.status_code == 200
        new_avatar = regen.json().get('avatar_url')
        assert new_avatar
        assert new_avatar != old_avatar
