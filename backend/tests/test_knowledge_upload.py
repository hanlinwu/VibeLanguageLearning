import os
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import User
from app.main import app


def _register_and_login(client: TestClient) -> tuple[str, str]:
    email = f"knowledge-{uuid.uuid4().hex[:8]}@example.com"
    payload = {'email': email, 'password': 'secret123', 'display_name': 'Tester'}
    reg = client.post('/auth/register', json=payload)
    assert reg.status_code == 201

    login = client.post('/auth/login', json={'email': payload['email'], 'password': payload['password']})
    assert login.status_code == 200
    return login.json()['access_token'], payload['email']


def test_upload_markdown_and_manage_multiple_bases() -> None:
    with TestClient(app) as client:
        token, _ = _register_and_login(client)
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


def test_public_base_requires_admin_to_create() -> None:
    with TestClient(app) as client:
        token, _ = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        create_public = client.post('/knowledge/bases', json={'name': '公共语法库', 'scope': 'public'}, headers=headers)
        assert create_public.status_code == 403


def test_public_base_is_visible_to_others_but_manageable_by_admin_only() -> None:
    with TestClient(app) as client:
        admin_token, admin_email = _register_and_login(client)
        user_token, _ = _register_and_login(client)
        admin_headers = {'Authorization': f'Bearer {admin_token}'}
        user_headers = {'Authorization': f'Bearer {user_token}'}

        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.email == admin_email).first()
            assert admin is not None
            admin.is_admin = True
            db.add(admin)
            db.commit()
        finally:
            db.close()

        create_public = client.post(
            '/knowledge/bases',
            json={'name': '公共语法库', 'scope': 'public'},
            headers=admin_headers,
        )
        assert create_public.status_code == 200
        public_base_id = create_public.json()['id']

        list_for_user = client.get('/knowledge/bases', headers=user_headers)
        assert list_for_user.status_code == 200
        public_base = next((item for item in list_for_user.json() if item['id'] == public_base_id), None)
        assert public_base is not None
        assert public_base['scope'] == 'public'
        assert public_base['can_manage'] is False

        update_by_user = client.patch(
            f'/knowledge/bases/{public_base_id}',
            json={'name': '我来改公共库'},
            headers=user_headers,
        )
        assert update_by_user.status_code == 403
