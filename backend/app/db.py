from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {'check_same_thread': False} if settings.database_url.startswith('sqlite') else {}
engine = create_engine(settings.database_url, echo=False, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def build_pgvector_bootstrap_sql(lists: int) -> list[str]:
    return [
        'CREATE EXTENSION IF NOT EXISTS vector',
        (
            'CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_ivfflat '
            'ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) '
            f'WITH (lists = {max(1, lists)})'
        ),
    ]


def bootstrap_pgvector(engine_obj: Engine, lists: int) -> None:
    if engine_obj.dialect.name != 'postgresql':
        return

    statements = build_pgvector_bootstrap_sql(lists=lists)
    with engine_obj.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
