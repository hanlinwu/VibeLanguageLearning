from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = 'AI Language Learn'
    secret_key: str = 'change-me'
    algorithm: str = 'HS256'
    access_token_expire_minutes: int = 60 * 24

    database_url: str = 'postgresql+psycopg://postgres:postgres@localhost:5432/ailanguagelearn'

    llm_base_url: str = 'https://api.openai.com/v1'
    llm_api_key: str = ''
    llm_chat_model: str = 'gpt-4o-mini'
    llm_embedding_model: str = 'text-embedding-3-small'
    llm_embedding_dimension: int = 1536
    pgvector_ivfflat_lists: int = 100

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
