import os

os.environ['DATABASE_URL'] = 'sqlite:///./test.db'

import pytest
import json

from app.config import get_settings
from app.llm_client import llm_client


@pytest.fixture(autouse=True)
def patch_llm_client(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()

    def fake_embed_text(text: str) -> list[float]:
        # Deterministic test embedding with configured dimension.
        return [0.01] * settings.llm_embedding_dimension

    def fake_chat(system_prompt: str, user_prompt: str) -> str:
        if '长期记忆提炼器' in system_prompt:
            if '更喜欢先听力后口语训练' in user_prompt:
                return json.dumps(
                    [
                        {
                            'category': 'preference',
                            'memory_key': 'preference:study_style',
                            'content': '用户更喜欢先听力后口语训练',
                            'importance': 0.93,
                            'reason': 'explicit-preference',
                        },
                        {
                            'category': 'grammar',
                            'memory_key': 'grammar:动词变位',
                            'content': '动词变位仍不熟练，需要持续复习',
                            'importance': 0.94,
                            'reason': 'mastery-gap',
                        },
                    ],
                    ensure_ascii=False,
                )
            return json.dumps(
                [
                    {
                        'category': 'preference',
                        'memory_key': 'preference:study_style',
                        'content': '用户喜欢先做语法练习',
                        'importance': 0.9,
                        'reason': 'explicit-preference',
                    },
                    {
                        'category': 'grammar',
                        'memory_key': 'grammar:动词变位',
                        'content': '动词变位是当前薄弱点',
                        'importance': 0.92,
                        'reason': 'mastery-gap',
                    },
                ],
                ensure_ascii=False,
            )
        return f'TEST_ANSWER: {user_prompt[:120]}'

    def fake_stream_chat(system_prompt: str, user_prompt: str):
        yield 'TEST_'
        yield 'STREAM_'
        yield 'ANSWER'

    def fake_chat_messages(messages: list[dict[str, str]]) -> str:
        # Simulate assistant response based on latest user turn.
        last_user = ''
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                last_user = msg.get('content', '')
                break
        return f'TEST_ANSWER: {last_user[:120]}'

    def fake_stream_chat_messages(messages: list[dict[str, str]]):
        yield 'TEST_'
        yield 'STREAM_'
        yield 'ANSWER'

    def fake_rerank_texts(query: str, documents: list[str], top_k: int):
        results: list[dict] = []
        lowered_query = query.lower()
        for idx, doc in enumerate(documents):
            lowered_doc = doc.lower()
            score = 0.09
            if 'etre' in lowered_query and 'etre' in lowered_doc:
                score = 0.95
            elif 'être' in lowered_query and 'être' in lowered_doc:
                score = 0.95
            results.append({'index': idx, 'score': score})
        return results[:top_k]

    monkeypatch.setattr(llm_client, 'embed_text', fake_embed_text)
    monkeypatch.setattr(llm_client, 'chat', fake_chat)
    monkeypatch.setattr(llm_client, 'stream_chat', fake_stream_chat)
    monkeypatch.setattr(llm_client, 'chat_messages', fake_chat_messages)
    monkeypatch.setattr(llm_client, 'stream_chat_messages', fake_stream_chat_messages)
    monkeypatch.setattr(llm_client, 'rerank_texts', fake_rerank_texts)
