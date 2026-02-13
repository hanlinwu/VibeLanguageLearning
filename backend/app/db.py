from collections.abc import Generator

from sqlalchemy import create_engine, exc, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {'check_same_thread': False} if settings.database_url.startswith('sqlite') else {}
engine = create_engine(settings.database_url, echo=False, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def ensure_pgvector_extension(engine_obj: Engine) -> None:
    if engine_obj.dialect.name != 'postgresql':
        return
    with engine_obj.begin() as conn:
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))


def bootstrap_pgvector_index(engine_obj: Engine, lists: int) -> None:
    if engine_obj.dialect.name != 'postgresql':
        return

    with engine_obj.begin() as conn:
        try:
            conn.execute(
                text(
                    'CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_ivfflat '
                    'ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) '
                    f'WITH (lists = {max(1, lists)})'
                )
            )
        except exc.DBAPIError:
            # knowledge_chunks may not exist yet during early bootstrap calls
            pass


def bootstrap_schema_compat(engine_obj: Engine) -> None:
    with engine_obj.begin() as conn:
        if engine_obj.dialect.name == 'postgresql':
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS target_language VARCHAR(64)'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500)'))
            conn.execute(
                text(
                    'ALTER TABLE interaction_logs '
                    'ADD COLUMN IF NOT EXISTS conversation_id INTEGER '
                    'REFERENCES chat_conversations(id)'
                )
            )
            conn.execute(text('ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL'))
            conn.execute(
                text(
                    'CREATE INDEX IF NOT EXISTS idx_interaction_logs_conversation_id '
                    'ON interaction_logs(conversation_id)'
                )
            )
            user_rows = conn.execute(
                text('SELECT DISTINCT user_id FROM interaction_logs WHERE conversation_id IS NULL')
            ).fetchall()
            for row in user_rows:
                user_id = int(row[0])
                conversation_id = conn.execute(
                    text(
                        'INSERT INTO chat_conversations(user_id, title, created_at, updated_at) '
                        "VALUES (:user_id, '历史会话', NOW(), NOW()) RETURNING id"
                    ),
                    {'user_id': user_id},
                ).scalar_one()
                conn.execute(
                    text(
                        'UPDATE interaction_logs '
                        'SET conversation_id = :conversation_id '
                        'WHERE user_id = :user_id AND conversation_id IS NULL'
                    ),
                    {'conversation_id': conversation_id, 'user_id': user_id},
                )

            conn.execute(
                text(
                    'ALTER TABLE knowledge_documents '
                    'ADD COLUMN IF NOT EXISTS knowledge_base_id INTEGER '
                    'REFERENCES knowledge_bases(id)'
                )
            )
            conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS scope VARCHAR(16)"))
            conn.execute(text("UPDATE knowledge_bases SET scope = COALESCE(scope, 'private')"))
            conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS status VARCHAR(24)"))
            conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS raw_content BYTEA'))
            conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS file_size INTEGER'))
            conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(120)"))
            conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL'))
            conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS progress INTEGER'))
            conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS total_chunks INTEGER'))
            conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS processed_chunks INTEGER'))
            conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER'))
            conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS error_message VARCHAR(300)'))
            conn.execute(
                text(
                    'CREATE INDEX IF NOT EXISTS idx_knowledge_documents_knowledge_base_id '
                    'ON knowledge_documents(knowledge_base_id)'
                )
            )
            conn.execute(text("UPDATE knowledge_documents SET status = COALESCE(status, 'completed')"))
            conn.execute(text('UPDATE knowledge_documents SET file_size = COALESCE(file_size, 0)'))
            conn.execute(text('UPDATE knowledge_documents SET progress = COALESCE(progress, 100)'))
            conn.execute(
                text(
                    'UPDATE knowledge_documents d '
                    'SET chunk_count = COALESCE(chunk_count, 0), '
                    'total_chunks = COALESCE(total_chunks, 0), '
                    'processed_chunks = COALESCE(processed_chunks, 0) '
                    'WHERE d.id IS NOT NULL'
                )
            )

            owner_rows = conn.execute(
                text('SELECT DISTINCT owner_id FROM knowledge_documents WHERE owner_id IS NOT NULL')
            ).fetchall()
            for row in owner_rows:
                owner_id = int(row[0])
                base_id = conn.execute(
                    text(
                        'SELECT id FROM knowledge_bases '
                        'WHERE owner_id = :owner_id ORDER BY created_at ASC LIMIT 1'
                    ),
                    {'owner_id': owner_id},
                ).scalar_one_or_none()
                if base_id is None:
                    base_id = conn.execute(
                        text(
                            'INSERT INTO knowledge_bases(owner_id, name, is_enabled, created_at, updated_at) '
                            "VALUES (:owner_id, '默认知识库', TRUE, NOW(), NOW()) RETURNING id"
                        ),
                        {'owner_id': owner_id},
                    ).scalar_one()
                conn.execute(
                    text(
                        'UPDATE knowledge_documents '
                        'SET knowledge_base_id = :base_id '
                        'WHERE owner_id = :owner_id AND knowledge_base_id IS NULL'
                    ),
                    {'base_id': int(base_id), 'owner_id': owner_id},
                )
            conn.execute(text('ALTER TABLE study_plan_units ADD COLUMN IF NOT EXISTS is_completed BOOLEAN DEFAULT FALSE'))
            conn.execute(text('ALTER TABLE study_plan_units ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP NULL'))
            conn.execute(
                text(
                    'ALTER TABLE study_plan_units '
                    'ADD COLUMN IF NOT EXISTS assessment_pass_score DOUBLE PRECISION DEFAULT 0.7'
                )
            )
            conn.execute(
                text('ALTER TABLE study_plan_units ADD COLUMN IF NOT EXISTS last_assessment_score DOUBLE PRECISION NULL')
            )
            conn.execute(text('ALTER TABLE study_plans ADD COLUMN IF NOT EXISTS questionnaire_json JSONB'))
            return

        if engine_obj.dialect.name == 'sqlite':
            user_columns = conn.execute(text("PRAGMA table_info('users')")).fetchall()
            user_column_names = {row[1] for row in user_columns}
            if 'is_admin' not in user_column_names:
                conn.execute(text('ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0'))
            if 'target_language' not in user_column_names:
                conn.execute(text('ALTER TABLE users ADD COLUMN target_language TEXT'))
            if 'avatar_url' not in user_column_names:
                conn.execute(text('ALTER TABLE users ADD COLUMN avatar_url TEXT'))

            columns = conn.execute(text("PRAGMA table_info('interaction_logs')")).fetchall()
            column_names = {row[1] for row in columns}
            if 'conversation_id' not in column_names:
                conn.execute(text('ALTER TABLE interaction_logs ADD COLUMN conversation_id INTEGER'))
            conv_columns = conn.execute(text("PRAGMA table_info('chat_conversations')")).fetchall()
            conv_column_names = {row[1] for row in conv_columns}
            if 'deleted_at' not in conv_column_names:
                conn.execute(text('ALTER TABLE chat_conversations ADD COLUMN deleted_at TEXT'))
            conn.execute(
                text(
                    'CREATE INDEX IF NOT EXISTS idx_interaction_logs_conversation_id '
                    'ON interaction_logs(conversation_id)'
                )
            )
            user_rows = conn.execute(
                text('SELECT DISTINCT user_id FROM interaction_logs WHERE conversation_id IS NULL')
            ).fetchall()
            for row in user_rows:
                user_id = int(row[0])
                conn.execute(
                    text(
                        "INSERT INTO chat_conversations(user_id, title, created_at, updated_at) "
                        "VALUES (:user_id, '历史会话', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {'user_id': user_id},
                )
                conversation_id = conn.execute(text('SELECT last_insert_rowid()')).scalar_one()
                conn.execute(
                    text(
                        'UPDATE interaction_logs '
                        'SET conversation_id = :conversation_id '
                        'WHERE user_id = :user_id AND conversation_id IS NULL'
                    ),
                    {'conversation_id': int(conversation_id), 'user_id': user_id},
                )

            doc_columns = conn.execute(text("PRAGMA table_info('knowledge_documents')")).fetchall()
            doc_column_names = {row[1] for row in doc_columns}
            if 'knowledge_base_id' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN knowledge_base_id INTEGER'))
            if 'status' not in doc_column_names:
                conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN status TEXT DEFAULT 'completed'"))
            if 'raw_content' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN raw_content BLOB'))
            if 'file_size' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN file_size INTEGER DEFAULT 0'))
            if 'embedding_model' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN embedding_model TEXT'))
            if 'deleted_at' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN deleted_at TEXT'))
            if 'progress' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN progress INTEGER DEFAULT 100'))
            if 'total_chunks' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN total_chunks INTEGER DEFAULT 0'))
            if 'processed_chunks' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN processed_chunks INTEGER DEFAULT 0'))
            if 'chunk_count' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN chunk_count INTEGER DEFAULT 0'))
            if 'error_message' not in doc_column_names:
                conn.execute(text('ALTER TABLE knowledge_documents ADD COLUMN error_message TEXT'))

            conn.execute(
                text(
                    'CREATE INDEX IF NOT EXISTS idx_knowledge_documents_knowledge_base_id '
                    'ON knowledge_documents(knowledge_base_id)'
                )
            )
            base_columns = conn.execute(text("PRAGMA table_info('knowledge_bases')")).fetchall()
            base_column_names = {row[1] for row in base_columns}
            if 'scope' not in base_column_names:
                conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN scope TEXT DEFAULT 'private'"))
            conn.execute(text("UPDATE knowledge_bases SET scope = COALESCE(scope, 'private')"))
            conn.execute(text("UPDATE knowledge_documents SET status = COALESCE(status, 'completed')"))
            conn.execute(text('UPDATE knowledge_documents SET file_size = COALESCE(file_size, 0)'))
            conn.execute(text('UPDATE knowledge_documents SET progress = COALESCE(progress, 100)'))
            conn.execute(
                text(
                    'UPDATE knowledge_documents '
                    'SET chunk_count = COALESCE(chunk_count, 0), '
                    'total_chunks = COALESCE(total_chunks, 0), '
                    'processed_chunks = COALESCE(processed_chunks, 0)'
                )
            )

            owner_rows = conn.execute(
                text('SELECT DISTINCT owner_id FROM knowledge_documents WHERE owner_id IS NOT NULL')
            ).fetchall()
            for row in owner_rows:
                owner_id = int(row[0])
                base_row = conn.execute(
                    text(
                        'SELECT id FROM knowledge_bases '
                        'WHERE owner_id = :owner_id ORDER BY created_at ASC LIMIT 1'
                    ),
                    {'owner_id': owner_id},
                ).fetchone()
                if base_row is None:
                    conn.execute(
                        text(
                            "INSERT INTO knowledge_bases(owner_id, name, is_enabled, created_at, updated_at) "
                            "VALUES (:owner_id, '默认知识库', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ),
                        {'owner_id': owner_id},
                    )
                    base_id = int(conn.execute(text('SELECT last_insert_rowid()')).scalar_one())
                else:
                    base_id = int(base_row[0])

                conn.execute(
                    text(
                        'UPDATE knowledge_documents '
                        'SET knowledge_base_id = :base_id '
                        'WHERE owner_id = :owner_id AND knowledge_base_id IS NULL'
                    ),
                    {'base_id': base_id, 'owner_id': owner_id},
                )

            spu_columns = conn.execute(text("PRAGMA table_info('study_plan_units')")).fetchall()
            spu_column_names = {row[1] for row in spu_columns}
            if 'is_completed' not in spu_column_names:
                conn.execute(text('ALTER TABLE study_plan_units ADD COLUMN is_completed INTEGER DEFAULT 0'))
            if 'completed_at' not in spu_column_names:
                conn.execute(text('ALTER TABLE study_plan_units ADD COLUMN completed_at TEXT'))
            if 'assessment_pass_score' not in spu_column_names:
                conn.execute(text('ALTER TABLE study_plan_units ADD COLUMN assessment_pass_score REAL DEFAULT 0.7'))
            if 'last_assessment_score' not in spu_column_names:
                conn.execute(text('ALTER TABLE study_plan_units ADD COLUMN last_assessment_score REAL'))

            sp_columns = conn.execute(text("PRAGMA table_info('study_plans')")).fetchall()
            sp_column_names = {row[1] for row in sp_columns}
            if 'questionnaire_json' not in sp_column_names:
                conn.execute(text('ALTER TABLE study_plans ADD COLUMN questionnaire_json TEXT'))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
