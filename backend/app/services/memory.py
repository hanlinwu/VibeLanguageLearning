from sqlalchemy.orm import Session

from app.models import LearningMemory


def get_or_create_memory(db: Session, user_id: int) -> LearningMemory:
    memory = db.query(LearningMemory).filter(LearningMemory.user_id == user_id).first()
    if memory:
        return memory

    memory = LearningMemory(user_id=user_id, mastery={}, weak_points=[], last_difficulty=1)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def update_memory_with_quiz(db: Session, user_id: int, weak_points: list[str], score_ratio: float) -> LearningMemory:
    memory = get_or_create_memory(db, user_id)
    memory.weak_points = weak_points[:10]
    memory.last_difficulty = max(1, min(5, int(round(score_ratio * 5))))
    db.commit()
    db.refresh(memory)
    return memory
