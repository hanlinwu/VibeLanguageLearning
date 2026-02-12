import math
from collections.abc import Sequence


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return -1.0
    return dot / (norm_a * norm_b)


def rank_by_similarity(question_embedding: list[float], candidates: list[dict], top_k: int = 4) -> list[dict]:
    scored = []
    for item in candidates:
        embedding = item.get('embedding', [])
        score = cosine_similarity(question_embedding, embedding)
        if score > -1:
            scored.append((item, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [item for item, _ in scored[:top_k]]
