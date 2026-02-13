from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_admin
from app.llm_client import llm_client
from app.models import ModelConfig, ModelProvider, User
from app.services.model_registry import (
    DEFAULT_EMBEDDING_SETTING_KEY,
    WEB_SEARCH_ENABLED_SETTING_KEY,
    WEB_SEARCH_PROVIDER_SETTING_KEY,
    WEB_SEARCH_SERPER_API_KEY_SETTING_KEY,
    WEB_SEARCH_SERPER_ENDPOINT_SETTING_KEY,
    get_setting,
    list_enabled_chat_models,
    resolve_web_search_settings,
    set_setting,
    sync_current_runtime_models,
)

router = APIRouter(prefix='/model-settings', tags=['model-settings'])


class ProviderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(min_length=1, max_length=255)
    is_enabled: bool = True


class ProviderUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=255)
    api_key: Optional[str] = Field(default=None, min_length=1, max_length=255)
    is_enabled: Optional[bool] = None


class ModelCreateRequest(BaseModel):
    provider_id: int
    model_name: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=160)
    model_type: str = Field(pattern='^(language|vision_language|reasoning|embedding)$')
    description: Optional[str] = Field(default=None, max_length=300)
    tags: list[str] = Field(default_factory=list)
    is_enabled: bool = True


class ModelUpdateRequest(BaseModel):
    model_name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    model_type: Optional[str] = Field(default=None, pattern='^(language|vision_language|reasoning|embedding)$')
    description: Optional[str] = Field(default=None, max_length=300)
    tags: Optional[list[str]] = None
    is_enabled: Optional[bool] = None


class SystemUpdateRequest(BaseModel):
    default_embedding_model_id: Optional[int] = None
    web_search_enabled: Optional[bool] = None
    web_search_provider: Optional[str] = Field(default=None, pattern='^(duckduckgo|serper)$')
    web_search_serper_api_key: Optional[str] = None
    web_search_serper_endpoint: Optional[str] = Field(default=None, max_length=255)


@router.get('/providers')
def list_providers(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> list[dict]:
    providers = db.query(ModelProvider).order_by(ModelProvider.updated_at.desc()).all()
    return [
        {
            'id': item.id,
            'name': item.name,
            'base_url': item.base_url,
            'is_enabled': item.is_enabled,
            'has_api_key': bool(item.api_key),
            'created_at': item.created_at.isoformat(),
            'updated_at': item.updated_at.isoformat(),
        }
        for item in providers
    ]


@router.post('/providers')
def create_provider(
    payload: ProviderCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> dict:
    provider = ModelProvider(
        name=payload.name.strip(),
        base_url=payload.base_url.strip(),
        api_key=payload.api_key.strip(),
        is_enabled=payload.is_enabled,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return {
        'id': provider.id,
        'name': provider.name,
        'base_url': provider.base_url,
        'is_enabled': provider.is_enabled,
        'has_api_key': bool(provider.api_key),
        'created_at': provider.created_at.isoformat(),
        'updated_at': provider.updated_at.isoformat(),
    }


@router.patch('/providers/{provider_id}')
def update_provider(
    provider_id: int,
    payload: ProviderUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> dict:
    provider = db.query(ModelProvider).filter(ModelProvider.id == provider_id).first()
    if provider is None:
        raise HTTPException(status_code=404, detail='Provider not found')
    if payload.name is not None:
        provider.name = payload.name.strip()
    if payload.base_url is not None:
        provider.base_url = payload.base_url.strip()
    if payload.api_key is not None:
        provider.api_key = payload.api_key.strip()
    if payload.is_enabled is not None:
        provider.is_enabled = payload.is_enabled
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return {
        'id': provider.id,
        'name': provider.name,
        'base_url': provider.base_url,
        'is_enabled': provider.is_enabled,
        'has_api_key': bool(provider.api_key),
        'created_at': provider.created_at.isoformat(),
        'updated_at': provider.updated_at.isoformat(),
    }


@router.get('/models')
def list_models(
    model_type: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> list[dict]:
    query = db.query(ModelConfig, ModelProvider).join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
    if model_type:
        query = query.filter(ModelConfig.model_type == model_type)
    rows = query.order_by(ModelConfig.updated_at.desc()).all()
    return [
        {
            'id': model.id,
            'provider_id': provider.id,
            'provider_name': provider.name,
            'model_name': model.model_name,
            'display_name': model.display_name,
            'model_type': model.model_type,
            'description': model.description,
            'tags': [item.strip() for item in (model.tags or '').split(',') if item.strip()],
            'is_enabled': model.is_enabled,
            'created_at': model.created_at.isoformat(),
            'updated_at': model.updated_at.isoformat(),
        }
        for model, provider in rows
    ]


@router.post('/models')
def create_model(
    payload: ModelCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> dict:
    provider = db.query(ModelProvider).filter(ModelProvider.id == payload.provider_id).first()
    if provider is None:
        raise HTTPException(status_code=404, detail='Provider not found')
    model = ModelConfig(
        provider_id=provider.id,
        model_name=payload.model_name.strip(),
        display_name=payload.display_name.strip(),
        model_type=payload.model_type,
        description=(payload.description or '').strip() or None,
        tags=','.join([item.strip() for item in payload.tags if item.strip()]) or None,
        is_enabled=payload.is_enabled,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return {
        'id': model.id,
        'provider_id': provider.id,
        'provider_name': provider.name,
        'model_name': model.model_name,
        'display_name': model.display_name,
        'model_type': model.model_type,
        'description': model.description,
        'tags': [item.strip() for item in (model.tags or '').split(',') if item.strip()],
        'is_enabled': model.is_enabled,
        'created_at': model.created_at.isoformat(),
        'updated_at': model.updated_at.isoformat(),
    }


@router.patch('/models/{model_id}')
def update_model(
    model_id: int,
    payload: ModelUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> dict:
    row = db.query(ModelConfig, ModelProvider).join(ModelProvider, ModelProvider.id == ModelConfig.provider_id).filter(
        ModelConfig.id == model_id
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail='Model not found')
    model, provider = row
    if payload.model_name is not None:
        model.model_name = payload.model_name.strip()
    if payload.display_name is not None:
        model.display_name = payload.display_name.strip()
    if payload.model_type is not None:
        model.model_type = payload.model_type
    if payload.description is not None:
        model.description = payload.description.strip() or None
    if payload.tags is not None:
        model.tags = ','.join([item.strip() for item in payload.tags if item.strip()]) or None
    if payload.is_enabled is not None:
        model.is_enabled = payload.is_enabled
    db.add(model)
    db.commit()
    db.refresh(model)
    return {
        'id': model.id,
        'provider_id': provider.id,
        'provider_name': provider.name,
        'model_name': model.model_name,
        'display_name': model.display_name,
        'model_type': model.model_type,
        'description': model.description,
        'tags': [item.strip() for item in (model.tags or '').split(',') if item.strip()],
        'is_enabled': model.is_enabled,
        'created_at': model.created_at.isoformat(),
        'updated_at': model.updated_at.isoformat(),
    }


@router.post('/models/{model_id}/test')
def test_model(
    model_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> dict:
    row = db.query(ModelConfig, ModelProvider).join(ModelProvider, ModelProvider.id == ModelConfig.provider_id).filter(
        ModelConfig.id == model_id
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail='Model not found')
    model, provider = row
    if model.model_type == 'embedding':
        llm_client.embed_text_with_provider('bonjour', provider.base_url, provider.api_key, model.model_name)
        return {'ok': True, 'message': 'embedding test passed'}
    llm_client.chat_messages_with_provider(
        [{'role': 'user', 'content': 'ping'}], provider.base_url, provider.api_key, model.model_name
    )
    return {'ok': True, 'message': 'chat test passed'}


@router.get('/system')
def get_system_settings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> dict:
    from app.services.model_registry import resolve_default_embedding_model

    resolved = resolve_default_embedding_model(db)
    web = resolve_web_search_settings(db)
    return {
        'default_embedding_model_id': resolved.model_id,
        'default_embedding_model_name': resolved.model_name,
        'web_search_enabled': web.enabled,
        'web_search_provider': web.provider,
        'web_search_serper_endpoint': web.serper_endpoint,
        'web_search_serper_has_api_key': bool(web.serper_api_key),
    }


@router.patch('/system')
def update_system_settings(
    payload: SystemUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> dict:
    if payload.default_embedding_model_id is None:
        set_setting(db, DEFAULT_EMBEDDING_SETTING_KEY, '')
    else:
        row = (
            db.query(ModelConfig)
            .filter(ModelConfig.id == payload.default_embedding_model_id, ModelConfig.model_type == 'embedding')
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail='Embedding model not found')
        set_setting(db, DEFAULT_EMBEDDING_SETTING_KEY, str(payload.default_embedding_model_id))
    if payload.web_search_enabled is not None:
        set_setting(db, WEB_SEARCH_ENABLED_SETTING_KEY, '1' if payload.web_search_enabled else '0')
    if payload.web_search_provider is not None:
        set_setting(db, WEB_SEARCH_PROVIDER_SETTING_KEY, payload.web_search_provider.strip().lower())
    if payload.web_search_serper_endpoint is not None:
        value = payload.web_search_serper_endpoint.strip() or 'https://google.serper.dev/search'
        set_setting(db, WEB_SEARCH_SERPER_ENDPOINT_SETTING_KEY, value)
    if payload.web_search_serper_api_key is not None:
        # Empty string means clear key intentionally.
        set_setting(db, WEB_SEARCH_SERPER_API_KEY_SETTING_KEY, payload.web_search_serper_api_key.strip())
    from app.services.model_registry import resolve_default_embedding_model

    resolved = resolve_default_embedding_model(db)
    web = resolve_web_search_settings(db)
    raw_provider = get_setting(db, WEB_SEARCH_PROVIDER_SETTING_KEY)
    return {
        'default_embedding_model_id': resolved.model_id,
        'default_embedding_model_name': resolved.model_name,
        'web_search_enabled': web.enabled,
        'web_search_provider': (raw_provider or web.provider),
        'web_search_serper_endpoint': web.serper_endpoint,
        'web_search_serper_has_api_key': bool(web.serper_api_key),
    }


@router.get('/chat-models')
def chat_models(db: Session = Depends(get_db)) -> list[dict]:
    return list_enabled_chat_models(db)


@router.post('/sync-current')
def sync_current_settings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> dict:
    return sync_current_runtime_models(db)
