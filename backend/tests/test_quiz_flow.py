import os
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.main import app


def _register_login(client: TestClient) -> str:
    email = f"quiz-{uuid.uuid4().hex[:8]}@example.com"
    payload = {'email': email, 'password': 'secret123', 'display_name': 'Tester'}
    reg = client.post('/auth/register', json=payload)
    assert reg.status_code == 201

    login = client.post('/auth/login', json={'email': payload['email'], 'password': payload['password']})
    assert login.status_code == 200
    return login.json()['access_token']


def test_generate_and_submit_quiz_updates_memory() -> None:
    with TestClient(app) as client:
        token = _register_login(client)

        gen = client.post('/quiz/generate', json={'num_questions': 6}, headers={'Authorization': f'Bearer {token}'})
        assert gen.status_code == 200
        body = gen.json()
        assert body['attempt_id'] > 0
        assert len(body['questions']) == 6

        answers = ['A'] * 6
        submit = client.post(
            '/quiz/submit',
            json={'attempt_id': body['attempt_id'], 'answers': answers},
            headers={'Authorization': f'Bearer {token}'},
        )
        assert submit.status_code == 200
        submit_body = submit.json()
        assert submit_body['total'] == 6
        assert 0 <= submit_body['score'] <= 1

        profile = client.get('/memory/profile', headers={'Authorization': f'Bearer {token}'})
        assert profile.status_code == 200
        assert 'last_difficulty' in profile.json()
