import os

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

import pytest

from app.config import get_settings
from app.llm_client import llm_client


@pytest.fixture(autouse=True)
def patch_llm_client(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()

    def fake_embed_text(text: str) -> list[float]:
        # Deterministic test embedding with configured dimension.
        return [0.01] * settings.llm_embedding_dimension

    def fake_chat(system_prompt: str, user_prompt: str) -> str:
        return f'TEST_ANSWER: {user_prompt[:120]}'

    def fake_stream_chat(system_prompt: str, user_prompt: str):
        yield 'TEST_'
        yield 'STREAM_'
        yield 'ANSWER'

    monkeypatch.setattr(llm_client, 'embed_text', fake_embed_text)
    monkeypatch.setattr(llm_client, 'chat', fake_chat)
    monkeypatch.setattr(llm_client, 'stream_chat', fake_stream_chat)
