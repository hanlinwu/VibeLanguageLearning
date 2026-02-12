import json
from collections.abc import Iterator

import httpx

from app.config import get_settings

settings = get_settings()


class LLMClient:
    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip('/')
        self.api_key = settings.llm_api_key

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError('LLM_API_KEY is required. Please set it in backend/.env')
        return {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}

    def embed_text(self, text: str) -> list[float]:
        payload = {'input': text, 'model': settings.llm_embedding_model}
        with httpx.Client(timeout=30) as client:
            resp = client.post(f'{self.base_url}/embeddings', headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data['data'][0]['embedding']

    def chat(self, system_prompt: str, user_prompt: str) -> str:
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

    def stream_chat(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        payload = {
            'model': settings.llm_chat_model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'temperature': 0.2,
            'stream': True,
        }
        with httpx.Client(timeout=120) as client:
            with client.stream(
                'POST',
                f'{self.base_url}/chat/completions',
                headers=self._headers(),
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
