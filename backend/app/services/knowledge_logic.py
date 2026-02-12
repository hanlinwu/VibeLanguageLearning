import json
from collections.abc import Iterable


def extract_text_payload(content: bytes, content_type: str) -> str:
    raw = content.decode('utf-8')
    if 'json' not in content_type:
        return raw

    data = json.loads(raw)
    if isinstance(data, dict):
        values: Iterable = data.values()
    elif isinstance(data, list):
        values = data
    else:
        return str(data)

    return '\n'.join(str(item) for item in values)


def split_chunks_stable(text: str, max_chars: int = 350) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ''

    for line in lines:
        if len(current) + len(line) + 1 > max_chars and current:
            chunks.append(current)
            current = line
        else:
            current = f'{current}\n{line}'.strip()

    if current:
        chunks.append(current)
    return chunks
