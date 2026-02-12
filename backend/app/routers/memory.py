from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import MemoryResponse
from app.services.memory import get_or_create_memory

router = APIRouter(prefix='/memory', tags=['memory'])


@router.get('/profile', response_model=MemoryResponse)
def profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> MemoryResponse:
    memory = get_or_create_memory(db, current_user.id)
    return MemoryResponse(
        mastery=memory.mastery,
        weak_points=memory.weak_points,
        last_difficulty=memory.last_difficulty,
    )
