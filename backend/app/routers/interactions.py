from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import ChatConversation, InteractionLog, User

router = APIRouter(prefix='/interactions', tags=['interactions'])


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


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
            'conversation_id': log.conversation_id,
            'question': log.question,
            'answer': log.answer,
            'trace_id': log.trace_id,
            'citations': log.citations,
            'created_at': log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.get('/conversations')
def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    conversations = (
        db.query(ChatConversation)
        .filter(ChatConversation.user_id == current_user.id, ChatConversation.deleted_at.is_(None))
        .order_by(ChatConversation.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            'id': item.id,
            'title': item.title,
            'created_at': item.created_at.isoformat(),
            'updated_at': item.updated_at.isoformat(),
        }
        for item in conversations
    ]


@router.get('/conversations/{conversation_id}/messages')
def list_conversation_messages(
    conversation_id: int,
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    conversation = (
        db.query(ChatConversation)
        .filter(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
            ChatConversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        return []

    logs = (
        db.query(InteractionLog)
        .filter(
            InteractionLog.user_id == current_user.id,
            InteractionLog.conversation_id == conversation_id,
        )
        .order_by(InteractionLog.created_at.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            'id': log.id,
            'conversation_id': log.conversation_id,
            'question': log.question,
            'answer': log.answer,
            'trace_id': log.trace_id,
            'citations': log.citations,
            'created_at': log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.patch('/conversations/{conversation_id}')
def rename_conversation(
    conversation_id: int,
    payload: ConversationRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    conversation = (
        db.query(ChatConversation)
        .filter(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
            ChatConversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        return {'updated': False}

    conversation.title = payload.title.strip()
    conversation.updated_at = datetime.utcnow()
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return {
        'updated': True,
        'id': conversation.id,
        'title': conversation.title,
        'updated_at': conversation.updated_at.isoformat(),
    }


@router.delete('/conversations/{conversation_id}')
def soft_delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    conversation = (
        db.query(ChatConversation)
        .filter(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
            ChatConversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        return {'deleted': False}

    conversation.deleted_at = datetime.utcnow()
    db.add(conversation)
    db.commit()
    return {'deleted': True}
