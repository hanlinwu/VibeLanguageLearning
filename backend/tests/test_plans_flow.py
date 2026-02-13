import os
import uuid
import time

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.main import app


def _register_and_login(client: TestClient) -> str:
    email = f"plan-{uuid.uuid4().hex[:8]}@example.com"
    payload = {'email': email, 'password': 'secret123', 'display_name': 'Planner'}
    reg = client.post('/auth/register', json=payload)
    assert reg.status_code == 201
    login = client.post('/auth/login', json={'email': email, 'password': payload['password']})
    assert login.status_code == 200
    return login.json()['access_token']


def _create_plan(client: TestClient, headers: dict, language_code: str = 'en') -> dict:
    res = client.post(
        '/plans',
        json={
            'language_code': language_code,
            'current_level': 'beginner',
            'self_assessment': '会少量词汇，几乎不能完整表达',
            'target_level': 'B1',
            'target_duration_weeks': 24,
        },
        headers=headers,
    )
    assert res.status_code == 201
    return res.json()


def test_create_plan_is_incremental_and_generate_next_level() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        created = _create_plan(client, headers, 'en')
        plan = created['plan']
        assert plan['status'] == 'active'
        assert plan['levels'] == []
        assert plan['generation']['generated_levels'] == 0
        assert plan['generation']['target_levels'] >= 3

        plan_id = plan['id']
        next_level = client.post(f'/plans/{plan_id}/generate-next-level', headers=headers)
        assert next_level.status_code == 200
        body = next_level.json()
        assert body['plan_id'] == plan_id
        assert body['generated_level'] is not None
        assert body['generated_level']['level_index'] == 1
        assert len(body['generated_level']['sections']) >= 1

        current = client.get('/plans/current', headers=headers)
        assert current.status_code == 200
        assert len(current.json()['plan']['levels']) == 1


def test_same_language_supports_multiple_plans_with_single_active() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        first = _create_plan(client, headers, 'fr')
        second = _create_plan(client, headers, 'fr')

        assert first['plan']['id'] != second['plan']['id']

        listed = client.get('/plans', headers=headers)
        assert listed.status_code == 200
        plans = listed.json()['plans']
        assert len(plans) >= 2
        active = [item for item in plans if item['status'] == 'active']
        assert len(active) == 1
        assert active[0]['id'] == second['plan']['id']

        activate_first = client.patch(f"/plans/{first['plan']['id']}/activate", headers=headers)
        assert activate_first.status_code == 200
        assert activate_first.json()['plan']['id'] == first['plan']['id']

        listed2 = client.get('/plans', headers=headers)
        assert listed2.status_code == 200
        active2 = [item for item in listed2.json()['plans'] if item['status'] == 'active']
        assert len(active2) == 1
        assert active2[0]['id'] == first['plan']['id']


def test_delete_plan_hard_delete() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        created = _create_plan(client, headers, 'ja')
        plan_id = created['plan']['id']
        next_level = client.post(f'/plans/{plan_id}/generate-next-level', headers=headers)
        assert next_level.status_code == 200

        deleted = client.delete(f'/plans/{plan_id}', headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()['deleted'] is True

        listed = client.get('/plans', headers=headers)
        assert listed.status_code == 200
        ids = [item['id'] for item in listed.json()['plans']]
        assert plan_id not in ids

        languages = client.get('/plans/languages', headers=headers)
        assert languages.status_code == 200
        assert languages.json()['languages'] == []


def test_class_assessment_pass_marks_class_completed() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        created = _create_plan(client, headers, 'en')
        plan_id = created['plan']['id']
        next_level = client.post(f'/plans/{plan_id}/generate-next-level', headers=headers)
        assert next_level.status_code == 200
        level_id = next_level.json()['generated_level']['id']

        generate_level_content = client.post(f'/plans/levels/{level_id}/generate-content', headers=headers)
        assert generate_level_content.status_code == 200
        first_class = generate_level_content.json()['sections'][0]['classes'][0]
        class_id = first_class['id']

        generated = client.post(f'/plans/classes/{class_id}/assessment/generate', headers=headers)
        assert generated.status_code == 200
        body = generated.json()
        assert body['attempt_id'] > 0
        assert len(body['questions']) >= 3

        answers = [str(item.get('answer', '')) for item in body['questions']]
        submitted = client.post(
            f'/plans/classes/{class_id}/assessment/submit',
            json={'attempt_id': body['attempt_id'], 'answers': answers},
            headers=headers,
        )
        assert submitted.status_code == 200
        submit_body = submitted.json()
        assert submit_body['passed'] is True
        assert submit_body['class_completed'] is True


def test_plan_generation_start_and_status() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        created = _create_plan(client, headers, 'en')
        plan_id = created['plan']['id']

        started = client.post(f'/plans/{plan_id}/generation/start', headers=headers)
        assert started.status_code == 200
        start_body = started.json()
        assert start_body['plan_id'] == plan_id
        assert start_body['status'] in {'running', 'completed'}
        assert start_body['target_levels'] >= 3

        # Worker may complete quickly in tests; accept running/completed.
        time.sleep(0.05)
        status_res = client.get(f'/plans/{plan_id}/generation/status', headers=headers)
        assert status_res.status_code == 200
        status_body = status_res.json()
        assert status_body['plan_id'] == plan_id
        assert status_body['status'] in {'idle', 'running', 'completed', 'failed'}


def test_iterative_assessment_pass_marks_previous_classes_completed() -> None:
    with TestClient(app) as client:
        token = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        created = _create_plan(client, headers, 'en')
        plan_id = created['plan']['id']

        lv1 = client.post(f'/plans/{plan_id}/generate-next-level', headers=headers)
        assert lv1.status_code == 200
        level1_id = lv1.json()['generated_level']['id']
        detail1 = client.post(f'/plans/levels/{level1_id}/generate-content', headers=headers)
        assert detail1.status_code == 200

        lv2 = client.post(f'/plans/{plan_id}/generate-next-level', headers=headers)
        assert lv2.status_code == 200
        level2_id = lv2.json()['generated_level']['id']
        detail2 = client.post(f'/plans/levels/{level2_id}/generate-content', headers=headers)
        assert detail2.status_code == 200

        classes_lv2 = detail2.json()['sections'][0]['classes']
        assert len(classes_lv2) >= 1
        target_class_id = classes_lv2[0]['id']

        started = client.post(f'/plans/classes/{target_class_id}/assessment/start', headers=headers)
        assert started.status_code == 200
        attempt_id = started.json()['attempt_id']
        total = started.json()['total_questions']
        assert total >= 3

        for idx in range(total):
            step = client.post(
                f'/plans/classes/{target_class_id}/assessment/step',
                json={'attempt_id': attempt_id, 'answer': f'answer-{idx + 1}'},
                headers=headers,
            )
            assert step.status_code == 200
            body = step.json()
            if idx < total - 1:
                assert body['done'] is False
                assert body['question'] is not None
            else:
                assert body['done'] is True
                assert body['passed'] is True
                assert body['class_completed'] is True
                assert body['completed_class_count'] >= 1

        current = client.get('/plans/current', headers=headers)
        assert current.status_code == 200
        all_classes = []
        for level in current.json()['plan']['levels']:
            for section in level['sections']:
                all_classes.extend(section['classes'])

        target = next(item for item in all_classes if item['id'] == target_class_id)
        assert target['is_completed'] is True
