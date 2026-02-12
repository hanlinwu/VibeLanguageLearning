import hashlib
import random
from typing import Optional

import httpx

from app.config import get_settings

settings = get_settings()


class LLMClient:
    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip('/')
        self.api_key = settings.llm_api_key

    def _headers(self) -> dict[str, str]:
        return {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}

    def embed_text(self, text: str) -> list[float]:
        if not self.api_key:
            return self._mock_embedding(text)

        payload = {'input': text, 'model': settings.llm_embedding_model}
        with httpx.Client(timeout=30) as client:
            resp = client.post(f'{self.base_url}/embeddings', headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data['data'][0]['embedding']

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key:
            return self._mock_answer(user_prompt)

        payload = {
            'model': settings.llm_chat_model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'temperature': 0.2,
        }
        with httpx.Client(timeout=60) as client:
            resp = client.post(f'{self.base_url}/chat/completions', headers=self._headers(), json=payload)
            resp.raise_for_status()
            return resp.json()['choices'][0]['message']['content']

    def _mock_embedding(self, text: str, size: Optional[int] = None) -> list[float]:
        if size is None:
            size = settings.llm_embedding_dimension
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        seed = int(digest[:8], 16)
        rng = random.Random(seed)
        return [rng.uniform(-1, 1) for _ in range(size)]

    def _mock_answer(self, prompt: str) -> str:
        return f'模拟回答: {prompt[:200]}'


llm_client = LLMClient()
