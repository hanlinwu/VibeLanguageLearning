import os
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.main import app


def _register_and_login(client: TestClient) -> str:
    email = f"historyquiz-{uuid.uuid4().hex[:8]}@example.com"
    payload = {'email': email, 'password': 'secret123', 'display_name': 'Tester'}
    reg = client.post('/auth/register', json=payload)
    assert reg.status_code == 201

    login = client.post('/auth/login', json={'email': payload['email'], 'password': payload['password']})
    assert login.status_code == 200
    return login.json()['access_token']


def _create_attempt(client: TestClient, token: str) -> int:
    generated = client.post('/quiz/generate', json={'num_questions': 4}, headers={'Authorization': f'Bearer {token}'})
    assert generated.status_code == 200
    return generated.json()['attempt_id']


def test_quiz_history_returns_latest_attempts() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        first = _create_attempt(client, token)
        second = _create_attempt(client, token)

        # Make sure attempts are submitted so score is available.
        submit = client.post(
            '/quiz/submit',
            json={'attempt_id': second, 'answers': ['A', 'A', 'A', 'A']},
            headers={'Authorization': f'Bearer {token}'},
        )
        assert submit.status_code == 200

        history = client.get('/quiz/history?limit=5', headers={'Authorization': f'Bearer {token}'})
        assert history.status_code == 200
        items = history.json()
        assert len(items) >= 2
        assert items[0]['attempt_id'] >= items[1]['attempt_id']
        assert 'score' in items[0]
        assert 'created_at' in items[0]


def test_wrong_questions_only_incorrect_items() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        attempt_id = _create_attempt(client, token)

        # Alternate correct/incorrect answers.
        submit = client.post(
            '/quiz/submit',
            json={'attempt_id': attempt_id, 'answers': ['A', 'X', 'A', 'X']},
            headers={'Authorization': f'Bearer {token}'},
        )
        assert submit.status_code == 200

        wrong = client.get('/quiz/wrong-questions?limit=10', headers={'Authorization': f'Bearer {token}'})
        assert wrong.status_code == 200
        items = wrong.json()
        assert len(items) == 2
        assert all(item['your_answer'] == 'X' for item in items)
        assert all('question' in item for item in items)
        assert all('correct_answer' in item for item in items)


def test_retry_wrong_creates_new_attempt_from_wrong_items() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        attempt_id = _create_attempt(client, token)

        submit = client.post(
            '/quiz/submit',
            json={'attempt_id': attempt_id, 'answers': ['A', 'X', 'A', 'X']},
            headers={'Authorization': f'Bearer {token}'},
        )
        assert submit.status_code == 200

        retry = client.post('/quiz/retry-wrong?limit=10', headers={'Authorization': f'Bearer {token}'})
        assert retry.status_code == 200
        body = retry.json()
        assert body['attempt_id'] > 0
        assert body['source_wrong_count'] == 2
        assert len(body['questions']) == 2


def test_wrong_questions_excludes_mastered_items_after_retry_correct() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        attempt_id = _create_attempt(client, token)

        # First attempt has 2 wrong answers.
        submit = client.post(
            '/quiz/submit',
            json={'attempt_id': attempt_id, 'answers': ['A', 'X', 'A', 'X']},
            headers={'Authorization': f'Bearer {token}'},
        )
        assert submit.status_code == 200

        retry = client.post('/quiz/retry-wrong?limit=10', headers={'Authorization': f'Bearer {token}'})
        assert retry.status_code == 200
        retry_body = retry.json()
        retry_attempt_id = retry_body['attempt_id']
        retry_answers = [item['answer'] for item in retry_body['questions']]

        # After retrying correctly, previous wrong items should be considered resolved.
        retry_submit = client.post(
            '/quiz/submit',
            json={'attempt_id': retry_attempt_id, 'answers': retry_answers},
            headers={'Authorization': f'Bearer {token}'},
        )
        assert retry_submit.status_code == 200

        wrong_after = client.get('/quiz/wrong-questions?limit=10', headers={'Authorization': f'Bearer {token}'})
        assert wrong_after.status_code == 200
        assert wrong_after.json() == []
