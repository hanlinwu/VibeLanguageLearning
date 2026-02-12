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
    llm_rerank_model: str = 'qwen3-reranker-4b'
    llm_rerank_min_score: float = 0.35
    llm_embedding_dimension: int = 1536
    pgvector_ivfflat_lists: int = 100
    cors_origins: str = 'http://127.0.0.1:5173,http://localhost:5173'
    admin_emails: str = ''

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    def get_cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(',') if item.strip()]

    def get_admin_emails(self) -> set[str]:
        return {item.strip().lower() for item in self.admin_emails.split(',') if item.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
