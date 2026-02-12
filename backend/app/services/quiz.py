from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, QuizAttempt
from app.services.memory import get_or_create_memory
from app.services.quiz_logic import build_questions, grade_answers


def generate_quiz(db: Session, user_id: int, num_questions: int) -> QuizAttempt:
    memory = get_or_create_memory(db, user_id)
    chunks = db.query(KnowledgeChunk).limit(max(1, num_questions)).all()
    texts = [chunk.text for chunk in chunks]
    weak_point = memory.weak_points[0] if memory.weak_points else 'general'
    questions = build_questions(texts, weak_point=weak_point, num_questions=num_questions)

    attempt = QuizAttempt(user_id=user_id, questions=questions, submitted_answers=None, score=None)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def grade_quiz(db: Session, attempt_id: int, answers: list[str]) -> tuple[QuizAttempt, int, int]:
    attempt = db.get(QuizAttempt, attempt_id)
    if not attempt:
        raise ValueError('Quiz attempt not found')

    expected = [str(q.get('answer', '')).strip().lower() for q in attempt.questions]
    correct, total, score = grade_answers(expected, answers)

    attempt.submitted_answers = answers
    attempt.score = score
    db.commit()
    db.refresh(attempt)

    return attempt, correct, total
