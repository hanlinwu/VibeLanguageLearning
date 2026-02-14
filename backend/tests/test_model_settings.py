import os
import uuid

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import ModelConfig, ModelProvider, User
from app.services import model_registry


def _register_login(client: TestClient, email_prefix: str) -> tuple[str, str]:
    email = f"{email_prefix}-{uuid.uuid4().hex[:8]}@example.com"
    payload = {'email': email, 'password': 'secret123', 'display_name': 'Tester'}
    reg = client.post('/auth/register', json=payload)
    assert reg.status_code == 201
    login = client.post('/auth/login', json={'email': email, 'password': 'secret123'})
    assert login.status_code == 200
    return login.json()['access_token'], email


def _set_admin(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        user.is_admin = True
        db.add(user)
        db.commit()
    finally:
        db.close()


def test_model_settings_admin_flow() -> None:
    with TestClient(app) as client:
        token, email = _register_login(client, 'ms-admin')
        _set_admin(email)
        headers = {'Authorization': f'Bearer {token}'}

        create_provider = client.post(
            '/model-settings/providers',
            json={'name': 'OpenAI', 'base_url': 'https://api.openai.com/v1', 'api_key': 'sk-test'},
            headers=headers,
        )
        assert create_provider.status_code == 200
        provider_id = create_provider.json()['id']

        create_chat_model = client.post(
            '/model-settings/models',
            json={
                'provider_id': provider_id,
                'model_name': 'gpt-4o-mini',
                'display_name': 'GPT-4o Mini',
                'model_type': 'language',
                'description': '通用对话模型',
                'tags': ['语言模型'],
            },
            headers=headers,
        )
        assert create_chat_model.status_code == 200

        create_embedding_model = client.post(
            '/model-settings/models',
            json={
                'provider_id': provider_id,
                'model_name': 'text-embedding-3-small',
                'display_name': 'Embedding Small',
                'model_type': 'embedding',
                'description': '向量化模型',
                'tags': ['embedding'],
            },
            headers=headers,
        )
        assert create_embedding_model.status_code == 200
        embedding_model_id = create_embedding_model.json()['id']

        set_default = client.patch(
            '/model-settings/system',
            json={
                'default_embedding_model_id': embedding_model_id,
                'web_search_enabled': True,
                'web_search_provider': 'serper',
                'web_search_serper_endpoint': 'https://google.serper.dev/search',
                'web_search_serper_api_key': 'serper-test-key',
            },
            headers=headers,
        )
        assert set_default.status_code == 200
        assert set_default.json()['default_embedding_model_id'] == embedding_model_id
        assert set_default.json()['web_search_enabled'] is True
        assert set_default.json()['web_search_provider'] == 'serper'
        assert set_default.json()['web_search_serper_has_api_key'] is True

        chat_models = client.get('/model-settings/chat-models', headers=headers)
        assert chat_models.status_code == 200
        assert any(item['display_name'] == 'GPT-4o Mini' for item in chat_models.json())


def test_model_settings_requires_admin() -> None:
    with TestClient(app) as client:
        token, _ = _register_login(client, 'ms-user')
        headers = {'Authorization': f'Bearer {token}'}
        create_provider = client.post(
            '/model-settings/providers',
            json={'name': 'OpenAI', 'base_url': 'https://api.openai.com/v1', 'api_key': 'sk-test'},
            headers=headers,
        )
        assert create_provider.status_code == 403


def test_model_settings_sync_current_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(model_registry.settings, 'llm_base_url', 'https://mock-provider.local/v1')
    monkeypatch.setattr(model_registry.settings, 'llm_api_key', 'mock-key')
    monkeypatch.setattr(model_registry.settings, 'llm_chat_model', 'mock-chat-model')
    monkeypatch.setattr(model_registry.settings, 'llm_embedding_model', 'mock-embedding-model')

    with TestClient(app) as client:
        token, email = _register_login(client, 'ms-sync-admin')
        _set_admin(email)
        headers = {'Authorization': f'Bearer {token}'}

        sync_once = client.post('/model-settings/sync-current', headers=headers)
        assert sync_once.status_code == 200
        payload_once = sync_once.json()
        assert payload_once['provider_id'] > 0
        assert payload_once['chat_model_id'] > 0
        assert payload_once['embedding_model_id'] > 0

        sync_twice = client.post('/model-settings/sync-current', headers=headers)
        assert sync_twice.status_code == 200
        payload_twice = sync_twice.json()

    db = SessionLocal()
    try:
        provider_rows = db.query(ModelProvider).filter(ModelProvider.name == model_registry.SYSTEM_PROVIDER_NAME).all()
        assert len(provider_rows) == 1
        provider = provider_rows[0]
        assert provider.base_url == 'https://mock-provider.local/v1'

        chat_model_rows = (
            db.query(ModelConfig)
            .filter(
                ModelConfig.provider_id == provider.id,
                ModelConfig.model_name == 'mock-chat-model',
                ModelConfig.model_type == 'language',
            )
            .all()
        )
        assert len(chat_model_rows) == 1

        embedding_model_rows = (
            db.query(ModelConfig)
            .filter(
                ModelConfig.provider_id == provider.id,
                ModelConfig.model_name == 'mock-embedding-model',
                ModelConfig.model_type == 'embedding',
            )
            .all()
        )
        assert len(embedding_model_rows) == 1
        assert payload_once['provider_id'] == payload_twice['provider_id']
        assert payload_once['chat_model_id'] == payload_twice['chat_model_id']
        assert payload_once['embedding_model_id'] == payload_twice['embedding_model_id']
    finally:
        db.close()


def test_model_and_provider_can_update_and_delete() -> None:
    with TestClient(app) as client:
        token, email = _register_login(client, 'ms-delete-admin')
        _set_admin(email)
        headers = {'Authorization': f'Bearer {token}'}

        provider = client.post(
            '/model-settings/providers',
            json={'name': 'DeleteMe', 'base_url': 'https://example.com/v1', 'api_key': 'sk-del'},
            headers=headers,
        )
        assert provider.status_code == 200
        provider_id = provider.json()['id']

        model = client.post(
            '/model-settings/models',
            json={
                'provider_id': provider_id,
                'model_name': 'to-delete-model',
                'display_name': 'To Delete',
                'model_type': 'language',
                'description': 'desc',
                'tags': ['语言模型'],
            },
            headers=headers,
        )
        assert model.status_code == 200
        model_id = model.json()['id']

        update_provider = client.patch(
            f'/model-settings/providers/{provider_id}',
            json={'name': 'DeleteMeUpdated'},
            headers=headers,
        )
        assert update_provider.status_code == 200
        assert update_provider.json()['name'] == 'DeleteMeUpdated'

        update_model = client.patch(
            f'/model-settings/models/{model_id}',
            json={'display_name': 'To Delete Updated'},
            headers=headers,
        )
        assert update_model.status_code == 200
        assert update_model.json()['display_name'] == 'To Delete Updated'

        # Provider with bound models cannot be deleted directly.
        provider_delete_blocked = client.delete(f'/model-settings/providers/{provider_id}', headers=headers)
        assert provider_delete_blocked.status_code == 400

        delete_model = client.delete(f'/model-settings/models/{model_id}', headers=headers)
        assert delete_model.status_code == 200
        assert delete_model.json()['deleted'] is True

        delete_provider = client.delete(f'/model-settings/providers/{provider_id}', headers=headers)
        assert delete_provider.status_code == 200
        assert delete_provider.json()['deleted'] is True
