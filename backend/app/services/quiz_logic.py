def build_questions(knowledge_texts: list[str], weak_point: str, num_questions: int) -> list[dict]:
    base = knowledge_texts if knowledge_texts else ['Connaissance de base']
    result: list[dict] = []

    for idx in range(num_questions):
        text = base[idx % len(base)]
        if idx % 2 == 0:
            result.append(
                {
                    'type': 'mcq',
                    'prompt': f'根据知识点回答：{text[:80]}',
                    'options': ['A', 'B', 'C', 'D'],
                    'answer': 'A',
                    'knowledge_point': weak_point or 'general',
                }
            )
        else:
            result.append(
                {
                    'type': 'fill_blank',
                    'prompt': f'填空：{text[:80]} ____',
                    'answer': 'A',
                    'knowledge_point': weak_point or 'general',
                }
            )

    return result


def grade_answers(expected: list[str], answers: list[str]) -> tuple[int, int, float]:
    normalized_expected = [item.strip().lower() for item in expected]
    normalized_answers = [item.strip().lower() for item in answers]
    total = len(normalized_expected)
    correct = sum(1 for a, b in zip(normalized_answers, normalized_expected) if a == b)
    score = correct / total if total else 0.0
    return correct, total, score
