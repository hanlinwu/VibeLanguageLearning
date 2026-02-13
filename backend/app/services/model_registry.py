from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ModelConfig, ModelProvider, SystemSetting

settings = get_settings()
DEFAULT_EMBEDDING_SETTING_KEY = 'default_embedding_model_id'
SYSTEM_PROVIDER_NAME = 'System Default Provider'
WEB_SEARCH_ENABLED_SETTING_KEY = 'web_search_enabled'
WEB_SEARCH_PROVIDER_SETTING_KEY = 'web_search_provider'
WEB_SEARCH_SERPER_API_KEY_SETTING_KEY = 'web_search_serper_api_key'
WEB_SEARCH_SERPER_ENDPOINT_SETTING_KEY = 'web_search_serper_endpoint'


@dataclass
class ResolvedModel:
    model_name: str
    base_url: str
    api_key: str
    model_id: Optional[int] = None


@dataclass
class WebSearchSettings:
    enabled: bool
    provider: str
    serper_endpoint: str
    serper_api_key: str


def _parse_tags(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(',') if item.strip()]


def list_enabled_chat_models(db: Session) -> list[dict]:
    rows = (
        db.query(ModelConfig, ModelProvider)
        .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
        .filter(
            ModelConfig.is_enabled.is_(True),
            ModelProvider.is_enabled.is_(True),
            ModelConfig.model_type.in_(['language', 'vision_language', 'reasoning']),
        )
        .order_by(ModelConfig.updated_at.desc())
        .all()
    )
    return [
        {
            'id': model.id,
            'provider_id': provider.id,
            'provider_name': provider.name,
            'model_name': model.model_name,
            'display_name': model.display_name,
            'model_type': model.model_type,
            'description': model.description,
            'tags': _parse_tags(model.tags),
        }
        for model, provider in rows
    ]


def resolve_chat_model(db: Session, model_id: Optional[int]) -> Optional[ResolvedModel]:
    if model_id is None:
        return None
    row = (
        db.query(ModelConfig, ModelProvider)
        .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
        .filter(
            ModelConfig.id == model_id,
            ModelConfig.is_enabled.is_(True),
            ModelProvider.is_enabled.is_(True),
            ModelConfig.model_type.in_(['language', 'vision_language', 'reasoning']),
        )
        .first()
    )
    if row is None:
        return None
    model, provider = row
    return ResolvedModel(
        model_name=model.model_name,
        base_url=provider.base_url,
        api_key=provider.api_key,
        model_id=model.id,
    )


def _get_setting(db: Session, key: str) -> Optional[str]:
    row = db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
    if row is None:
        return None
    return row.setting_value


def get_setting(db: Session, key: str) -> Optional[str]:
    return _get_setting(db, key)


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
    if row is None:
        row = SystemSetting(setting_key=key, setting_value=value)
    else:
        row.setting_value = value
    db.add(row)
    db.commit()


def resolve_web_search_settings(db: Session) -> WebSearchSettings:
    raw_enabled = (_get_setting(db, WEB_SEARCH_ENABLED_SETTING_KEY) or '').strip().lower()
    enabled = raw_enabled in {'1', 'true', 'yes', 'on'}
    provider = (_get_setting(db, WEB_SEARCH_PROVIDER_SETTING_KEY) or 'duckduckgo').strip().lower()
    if provider not in {'duckduckgo', 'serper'}:
        provider = 'duckduckgo'
    serper_endpoint = (
        _get_setting(db, WEB_SEARCH_SERPER_ENDPOINT_SETTING_KEY) or 'https://google.serper.dev/search'
    ).strip()
    if not serper_endpoint:
        serper_endpoint = 'https://google.serper.dev/search'
    serper_api_key = (_get_setting(db, WEB_SEARCH_SERPER_API_KEY_SETTING_KEY) or '').strip()
    return WebSearchSettings(
        enabled=enabled,
        provider=provider,
        serper_endpoint=serper_endpoint,
        serper_api_key=serper_api_key,
    )


def _upsert_model(
    db: Session,
    *,
    provider_id: int,
    model_name: str,
    display_name: str,
    model_type: str,
    description: str,
    tags: str,
) -> ModelConfig:
    model = (
        db.query(ModelConfig)
        .filter(
            ModelConfig.provider_id == provider_id,
            ModelConfig.model_name == model_name,
            ModelConfig.model_type == model_type,
        )
        .first()
    )
    if model is None:
        model = ModelConfig(
            provider_id=provider_id,
            model_name=model_name,
            display_name=display_name,
            model_type=model_type,
            description=description,
            tags=tags,
            is_enabled=True,
        )
        db.add(model)
        db.flush()
        return model
    model.display_name = display_name
    model.description = description
    model.tags = tags
    model.is_enabled = True
    db.add(model)
    db.flush()
    return model


def sync_current_runtime_models(db: Session) -> dict:
    provider = db.query(ModelProvider).filter(ModelProvider.name == SYSTEM_PROVIDER_NAME).first()
    if provider is None:
        provider = ModelProvider(
            name=SYSTEM_PROVIDER_NAME,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            is_enabled=True,
        )
        db.add(provider)
        db.flush()
    else:
        provider.base_url = settings.llm_base_url
        provider.api_key = settings.llm_api_key
        provider.is_enabled = True
        db.add(provider)
        db.flush()

    chat_model = _upsert_model(
        db,
        provider_id=provider.id,
        model_name=settings.llm_chat_model,
        display_name=f'{settings.llm_chat_model} (系统默认)',
        model_type='language',
        description='来自环境变量 LLM_CHAT_MODEL',
        tags='default,chat',
    )
    embedding_model = _upsert_model(
        db,
        provider_id=provider.id,
        model_name=settings.llm_embedding_model,
        display_name=f'{settings.llm_embedding_model} (系统默认)',
        model_type='embedding',
        description='来自环境变量 LLM_EMBEDDING_MODEL',
        tags='default,embedding',
    )
    db.commit()

    raw_embedding_model_id = _get_setting(db, DEFAULT_EMBEDDING_SETTING_KEY)
    should_set_default = not raw_embedding_model_id
    if raw_embedding_model_id:
        try:
            stored_id = int(raw_embedding_model_id)
        except ValueError:
            stored_id = 0
        if stored_id <= 0:
            should_set_default = True
        else:
            existing = db.query(ModelConfig).filter(ModelConfig.id == stored_id, ModelConfig.model_type == 'embedding').first()
            should_set_default = existing is None
    if should_set_default:
        set_setting(db, DEFAULT_EMBEDDING_SETTING_KEY, str(embedding_model.id))

    effective_default_embedding_model_id = embedding_model.id if should_set_default else None
    if not should_set_default and raw_embedding_model_id:
        try:
            effective_default_embedding_model_id = int(raw_embedding_model_id)
        except ValueError:
            effective_default_embedding_model_id = None

    return {
        'provider_id': provider.id,
        'chat_model_id': chat_model.id,
        'embedding_model_id': embedding_model.id,
        'default_embedding_model_id': effective_default_embedding_model_id,
    }


def resolve_default_embedding_model(db: Session) -> ResolvedModel:
    raw_model_id = _get_setting(db, DEFAULT_EMBEDDING_SETTING_KEY)
    if raw_model_id:
        try:
            model_id = int(raw_model_id)
        except ValueError:
            model_id = 0
        if model_id > 0:
            row = (
                db.query(ModelConfig, ModelProvider)
                .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
                .filter(
                    ModelConfig.id == model_id,
                    ModelConfig.model_type == 'embedding',
                    ModelConfig.is_enabled.is_(True),
                    ModelProvider.is_enabled.is_(True),
                )
                .first()
            )
            if row is not None:
                model, provider = row
                return ResolvedModel(
                    model_name=model.model_name,
                    base_url=provider.base_url,
                    api_key=provider.api_key,
                    model_id=model.id,
                )

    return ResolvedModel(
        model_name=settings.llm_embedding_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model_id=None,
    )
