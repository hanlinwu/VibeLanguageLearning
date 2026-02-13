import os
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.main import app


def _register_login_seed_and_query(client: TestClient) -> str:
    email = f"history-{uuid.uuid4().hex[:8]}@example.com"
    payload = {'email': email, 'password': 'secret123', 'display_name': 'Tester'}
    reg = client.post('/auth/register', json=payload)
    assert reg.status_code == 201

    login = client.post('/auth/login', json={'email': payload['email'], 'password': payload['password']})
    assert login.status_code == 200
    token = login.json()['access_token']

    files = {'file': ('history.md', b'Le verbe etre: je suis, tu es.', 'text/markdown')}
    upload = client.post('/knowledge/upload', files=files, headers={'Authorization': f'Bearer {token}'})
    assert upload.status_code == 200

    query = client.post('/query', json={'question': 'Que signifie etre?'}, headers={'Authorization': f'Bearer {token}'})
    assert query.status_code == 200
    return token


def test_recent_interactions_returns_user_history() -> None:
    with TestClient(app) as client:
        token = _register_login_seed_and_query(client)
        history = client.get('/interactions/recent?limit=5', headers={'Authorization': f'Bearer {token}'})

        assert history.status_code == 200
        items = history.json()
        assert isinstance(items, list)
        assert len(items) >= 1
        assert 'question' in items[0]
        assert 'answer' in items[0]
        assert 'trace_id' in items[0]


def test_home_dashboard_returns_summary() -> None:
    with TestClient(app) as client:
        token = _register_login_seed_and_query(client)
        res = client.get('/interactions/home-dashboard', headers={'Authorization': f'Bearer {token}'})
        assert res.status_code == 200
        body = res.json()
        assert 'streak_days' in body
        assert 'plan_progress' in body
        assert 'milestones' in body
