import json
import logging
from collections.abc import Iterator
from typing import Union

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip('/')
        self.api_key = settings.llm_api_key

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError('LLM_API_KEY is required. Please set it in backend/.env')
        return {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}

    def _headers_for_key(self, api_key: str) -> dict[str, str]:
        key = (api_key or '').strip()
        if not key:
            raise RuntimeError('API key is required')
        return {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}

    def embed_text(self, text: str) -> list[float]:
        return self.embed_text_with_provider(text, settings.llm_base_url, self.api_key, settings.llm_embedding_model)

    def embed_text_with_provider(self, text: str, base_url: str, api_key: str, model: str) -> list[float]:
        payload = {'input': text, 'model': model}
        endpoint = base_url.rstrip('/')
        with httpx.Client(timeout=30) as client:
            resp = client.post(f'{endpoint}/embeddings', headers=self._headers_for_key(api_key), json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data['data'][0]['embedding']

    def rerank_texts(self, query: str, documents: list[str], top_k: int) -> list[dict[str, Union[float, int]]]:
        model = settings.llm_rerank_model.strip()
        if not model or not documents:
            return []
        payload = {
            'model': model,
            'query': query,
            'documents': documents,
            'top_n': min(max(top_k, 1), len(documents)),
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(f'{self.base_url}/rerank', headers=self._headers(), json=payload)
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:
            logger.warning('rerank request failed: %s', exc)
            return []

        results = body.get('results') or body.get('data') or []
        parsed: list[dict[str, Union[float, int]]] = []
        for item in results:
            idx = item.get('index')
            if not isinstance(idx, int):
                continue
            raw_score = item.get('relevance_score', item.get('score', 0.0))
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                continue
            parsed.append({'index': idx, 'score': score})
        parsed.sort(key=lambda entry: float(entry['score']), reverse=True)
        return parsed[:top_k]

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        return self.chat_messages(
            [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ]
        )

    def chat_messages(self, messages: list[dict[str, str]]) -> str:
        return self.chat_messages_with_provider(messages, settings.llm_base_url, self.api_key, settings.llm_chat_model)

    def chat_messages_with_provider(
        self, messages: list[dict[str, str]], base_url: str, api_key: str, model: str
    ) -> str:
        payload = {
            'model': model,
            'messages': messages,
            'temperature': 0.2,
        }
        endpoint = base_url.rstrip('/')
        with httpx.Client(timeout=60) as client:
            resp = client.post(f'{endpoint}/chat/completions', headers=self._headers_for_key(api_key), json=payload)
            resp.raise_for_status()
            return resp.json()['choices'][0]['message']['content']

    def stream_chat(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        yield from self.stream_chat_messages(
            [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ]
        )

    def stream_chat_messages(self, messages: list[dict[str, str]]) -> Iterator[str]:
        yield from self.stream_chat_messages_with_provider(messages, settings.llm_base_url, self.api_key, settings.llm_chat_model)

    def stream_chat_messages_with_provider(
        self,
        messages: list[dict[str, str]],
        base_url: str,
        api_key: str,
        model: str,
    ) -> Iterator[str]:
        payload = {
            'model': model,
            'messages': messages,
            'temperature': 0.2,
            'stream': True,
        }
        endpoint = base_url.rstrip('/')
        with httpx.Client(timeout=120) as client:
            with client.stream(
                'POST',
                f'{endpoint}/chat/completions',
                headers=self._headers_for_key(api_key),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if not line.startswith('data:'):
                        continue
                    data = line[len('data:') :].strip()
                    if data == '[DONE]':
                        break
                    try:
                        payload_obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = payload_obj.get('choices', [{}])[0].get('delta', {})
                    content = delta.get('content')
                    if content:
                        yield content


llm_client = LLMClient()
