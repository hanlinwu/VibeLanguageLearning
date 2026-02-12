from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import QuizAttempt, User
from app.schemas import QuizGenerateRequest, QuizGenerateResponse, QuizSubmitRequest, QuizSubmitResponse
from app.services.memory import update_memory_with_quiz
from app.services.quiz import generate_quiz, grade_quiz

router = APIRouter(prefix='/quiz', tags=['quiz'])


@router.post('/generate', response_model=QuizGenerateResponse)
def generate(
    payload: QuizGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuizGenerateResponse:
    attempt = generate_quiz(db, current_user.id, payload.num_questions)
    return QuizGenerateResponse(attempt_id=attempt.id, questions=attempt.questions)


@router.post('/submit', response_model=QuizSubmitResponse)
def submit(
    payload: QuizSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuizSubmitResponse:
    try:
        attempt, correct, total = grade_quiz(db, payload.attempt_id, payload.answers)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    weak_points = [] if attempt.score and attempt.score > 0.6 else ['conjugation']
    update_memory_with_quiz(db, current_user.id, weak_points=weak_points, score_ratio=attempt.score or 0.0)
    return QuizSubmitResponse(score=attempt.score or 0.0, total=total, correct=correct)


@router.get('/history')
def history(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.user_id == current_user.id)
        .order_by(QuizAttempt.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            'attempt_id': attempt.id,
            'score': attempt.score,
            'total_questions': len(attempt.questions or []),
            'created_at': attempt.created_at.isoformat(),
        }
        for attempt in attempts
    ]


@router.get('/wrong-questions')
def wrong_questions(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.user_id == current_user.id)
        .order_by(QuizAttempt.created_at.desc())
        .all()
    )

    result: list[dict] = []
    resolved_keys: set[str] = set()
    for attempt in attempts:
        questions = attempt.questions or []
        answers = attempt.submitted_answers or []
        for idx, question in enumerate(questions):
            expected = str(question.get('answer', '')).strip().lower()
            actual = str(answers[idx]).strip().lower() if idx < len(answers) else ''
            qtype = str(question.get('type', 'unknown')).strip().lower()
            prompt = str(question.get('prompt', '')).strip().lower()
            key = f'{qtype}|{prompt}|{expected}'

            if actual == expected:
                resolved_keys.add(key)
                continue

            if key in resolved_keys:
                continue

            if actual != expected:
                result.append(
                    {
                        'attempt_id': attempt.id,
                        'index': idx,
                        'type': question.get('type', 'unknown'),
                        'question': question.get('prompt', ''),
                        'your_answer': answers[idx] if idx < len(answers) else '',
                        'correct_answer': question.get('answer', ''),
                    }
                )
            if len(result) >= limit:
                return result

    return result


@router.post('/retry-wrong')
def retry_wrong_questions(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    wrong_items = wrong_questions(limit=limit, db=db, current_user=current_user)
    if not wrong_items:
        return {'attempt_id': None, 'source_wrong_count': 0, 'questions': []}

    questions = []
    for item in wrong_items:
        questions.append(
            {
                'type': item['type'],
                'prompt': item['question'],
                'answer': item['correct_answer'],
                'knowledge_point': 'wrong_book_retry',
            }
        )

    attempt = QuizAttempt(user_id=current_user.id, questions=questions, submitted_answers=None, score=None)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return {'attempt_id': attempt.id, 'source_wrong_count': len(wrong_items), 'questions': attempt.questions}
