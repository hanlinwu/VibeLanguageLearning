from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import (
    MemoryItemUpdateRequest,
    MemoryResponse,
    MemoryStreamResponse,
)
from app.services.memory import (
    get_or_create_memory,
    list_memory_stream,
    soft_delete_memory_item,
    update_memory_item,
)

router = APIRouter(prefix='/memory', tags=['memory'])


@router.get('/profile', response_model=MemoryResponse)
def profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> MemoryResponse:
    memory = get_or_create_memory(db, current_user.id)
    return MemoryResponse(
        mastery=memory.mastery,
        weak_points=memory.weak_points,
        last_difficulty=memory.last_difficulty,
    )


@router.get('/stream', response_model=MemoryStreamResponse)
def stream(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> MemoryStreamResponse:
    payload = list_memory_stream(db, current_user.id)
    return MemoryStreamResponse(
        items=[
            {
                'id': item.id,
                'category': item.category,
                'memory_key': item.memory_key,
                'content': item.content,
                'importance': item.importance,
                'source_conversation_id': item.source_conversation_id,
                'source_interaction_id': item.source_interaction_id,
                'created_at': item.created_at.isoformat(),
                'updated_at': item.updated_at.isoformat(),
            }
            for item in payload['items']
        ],
        changes=[
            {
                'id': change.id,
                'item_id': change.item_id,
                'action': change.action,
                'reason': change.reason,
                'before_state': change.before_state or {},
                'after_state': change.after_state or {},
                'source_conversation_id': change.source_conversation_id,
                'source_interaction_id': change.source_interaction_id,
                'created_at': change.created_at.isoformat(),
            }
            for change in payload['changes']
        ],
    )


@router.patch('/items/{item_id}')
def patch_item(
    item_id: int,
    payload: MemoryItemUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    item = update_memory_item(
        db,
        current_user.id,
        item_id=item_id,
        content=payload.content,
        importance=payload.importance,
        reason=(payload.reason or 'manual-update').strip()[:200],
    )
    if item is None:
        raise HTTPException(status_code=404, detail='记忆项不存在')
    db.commit()
    return {'updated': True, 'id': item.id}


@router.delete('/items/{item_id}')
def delete_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    deleted = soft_delete_memory_item(db, current_user.id, item_id=item_id, reason='manual-delete')
    if not deleted:
        raise HTTPException(status_code=404, detail='记忆项不存在')
    db.commit()
    return {'deleted': True, 'id': item_id}
