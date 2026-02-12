from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import Base, bootstrap_pgvector, engine
from app.routers import auth, interactions, knowledge, memory, query, quiz

app = FastAPI(title='AI Language Learn API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.on_event('startup')
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    settings = get_settings()
    bootstrap_pgvector(engine, lists=settings.pgvector_ivfflat_lists)


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}


app.include_router(auth.router)
app.include_router(interactions.router)
app.include_router(knowledge.router)
app.include_router(query.router)
app.include_router(quiz.router)
app.include_router(memory.router)
