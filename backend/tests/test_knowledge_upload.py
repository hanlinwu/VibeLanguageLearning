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
        assert isinstance(item.get('file_size'), int)
        assert item.get('file_size', 0) > 0
        assert item.get('created_at')
        assert 'chunk_count' in item
        assert 'processed_chunks' in item
        assert 'total_chunks' in item

        bases = client.get('/knowledge/bases', headers=headers)
        assert bases.status_code == 200
        assert any(item['id'] == base_id for item in bases.json())


def test_can_download_original_uploaded_file() -> None:
    with TestClient(app) as client:
        token, _ = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        create_base = client.post('/knowledge/bases', json={'name': '下载测试库'}, headers=headers)
        assert create_base.status_code == 200
        base_id = create_base.json()['id']

        raw = b'# Bonjour\\nLe present de etre.'
        files = {'file': ('french.md', raw, 'text/markdown')}
        upload = client.post(f'/knowledge/upload?knowledge_base_id={base_id}', files=files, headers=headers)
        assert upload.status_code == 200
        document_id = upload.json()['document_id']

        download = client.get(f'/knowledge/docs/{document_id}/download', headers=headers)
        assert download.status_code == 200
        assert download.content == raw
        disposition = download.headers.get('content-disposition', '')
        assert 'attachment' in disposition.lower()
        assert 'french.md' in disposition


def test_can_download_original_uploaded_file_with_unicode_filename() -> None:
    with TestClient(app) as client:
        token, _ = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        create_base = client.post('/knowledge/bases', json={'name': '下载测试库2'}, headers=headers)
        assert create_base.status_code == 200
        base_id = create_base.json()['id']

        raw = '法语笔记内容'.encode('utf-8')
        files = {'file': ('法语笔记.md', raw, 'text/markdown')}
        upload = client.post(f'/knowledge/upload?knowledge_base_id={base_id}', files=files, headers=headers)
        assert upload.status_code == 200
        document_id = upload.json()['document_id']

        download = client.get(f'/knowledge/docs/{document_id}/download', headers=headers)
        assert download.status_code == 200
        assert download.content == raw
        disposition = download.headers.get('content-disposition', '')
        assert 'attachment' in disposition.lower()
        assert 'filename*=' in disposition


def test_can_delete_document_from_knowledge_base() -> None:
    with TestClient(app) as client:
        token, _ = _register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}

        create_base = client.post('/knowledge/bases', json={'name': '删除测试库'}, headers=headers)
        assert create_base.status_code == 200
        base_id = create_base.json()['id']

        files = {'file': ('to-delete.md', b'bonjour monde', 'text/markdown')}
        upload = client.post(f'/knowledge/upload?knowledge_base_id={base_id}', files=files, headers=headers)
        assert upload.status_code == 200
        document_id = upload.json()['document_id']

        delete_resp = client.delete(f'/knowledge/docs/{document_id}', headers=headers)
        assert delete_resp.status_code == 200
        assert delete_resp.json().get('deleted') is True

        docs = client.get(f'/knowledge/docs?knowledge_base_id={base_id}', headers=headers)
        assert docs.status_code == 200
        assert all(item['id'] != document_id for item in docs.json())

        deleted_docs = client.get(f'/knowledge/docs?knowledge_base_id={base_id}&include_deleted=true', headers=headers)
        assert deleted_docs.status_code == 200
        target = next((item for item in deleted_docs.json() if item['id'] == document_id), None)
        assert target is not None
        assert target.get('deleted_at')

        download = client.get(f'/knowledge/docs/{document_id}/download', headers=headers)
        assert download.status_code == 404

        restore_resp = client.post(f'/knowledge/docs/{document_id}/restore', headers=headers)
        assert restore_resp.status_code == 200
        assert restore_resp.json().get('restored') is True

        docs_after_restore = client.get(f'/knowledge/docs?knowledge_base_id={base_id}', headers=headers)
        assert docs_after_restore.status_code == 200
        assert any(item['id'] == document_id for item in docs_after_restore.json())


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
