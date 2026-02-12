from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import InteractionLog, User

router = APIRouter(prefix='/interactions', tags=['interactions'])


@router.get('/recent')
def recent_interactions(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    logs = (
        db.query(InteractionLog)
        .filter(InteractionLog.user_id == current_user.id)
        .order_by(InteractionLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            'id': log.id,
            'question': log.question,
            'answer': log.answer,
            'trace_id': log.trace_id,
            'citations': log.citations,
            'created_at': log.created_at.isoformat(),
        }
        for log in logs
    ]
