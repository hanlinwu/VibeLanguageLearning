from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import Base, SessionLocal, bootstrap_pgvector_index, bootstrap_schema_compat, engine, ensure_pgvector_extension
from app.routers import auth, interactions, knowledge, memory, model_settings, plans, query, quiz
from app.services.model_registry import sync_current_runtime_models

app = FastAPI(title='AI Language Learn API')
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.on_event('startup')
def on_startup() -> None:
    ensure_pgvector_extension(engine)
    Base.metadata.create_all(bind=engine)
    bootstrap_schema_compat(engine)
    bootstrap_pgvector_index(engine, lists=settings.pgvector_ivfflat_lists)
    db = SessionLocal()
    try:
        sync_current_runtime_models(db)
    finally:
        db.close()


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}


app.include_router(auth.router)
app.include_router(interactions.router)
app.include_router(knowledge.router)
app.include_router(query.router)
app.include_router(quiz.router)
app.include_router(memory.router)
app.include_router(model_settings.router)
app.include_router(plans.router)
