from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import ChatConversation, InteractionLog, QuizAttempt, StudyPlan, StudyPlanLevel, StudyPlanUnit, User, UserLanguageProfile

router = APIRouter(prefix='/interactions', tags=['interactions'])


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def _calc_streak_days(activity_days: list[datetime.date]) -> int:
    if not activity_days:
        return 0
    unique_days = sorted({d for d in activity_days}, reverse=True)
    streak = 1
    cursor = unique_days[0]
    for day in unique_days[1:]:
        if (cursor - day).days == 1:
            streak += 1
            cursor = day
            continue
        break
    return streak


@router.get('/home-dashboard')
def home_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    logs = db.query(InteractionLog).filter(InteractionLog.user_id == current_user.id).all()
    quizzes = db.query(QuizAttempt).filter(QuizAttempt.user_id == current_user.id).all()
    activity_days = [item.created_at.date() for item in logs] + [item.created_at.date() for item in quizzes]
    streak_days = _calc_streak_days(activity_days)

    now = datetime.utcnow()
    week_start = (now - timedelta(days=6)).date()
    week_activity_days = len({d for d in activity_days if d >= week_start})
    week_interactions = sum(1 for item in logs if item.created_at.date() >= week_start)
    week_quizzes = sum(1 for item in quizzes if item.created_at.date() >= week_start)

    active_profile = (
        db.query(UserLanguageProfile)
        .filter(
            UserLanguageProfile.user_id == current_user.id,
            UserLanguageProfile.is_active.is_(True),
        )
        .order_by(UserLanguageProfile.updated_at.desc())
        .first()
    )

    current_level = None
    total_classes = 0
    completed_classes = 0
    completed_recent = 0
    if active_profile is not None:
        plan = (
            db.query(StudyPlan)
            .filter(
                StudyPlan.user_id == current_user.id,
                StudyPlan.language_profile_id == active_profile.id,
                StudyPlan.status == 'active',
            )
            .order_by(StudyPlan.created_at.desc())
            .first()
        )
        if plan is not None:
            levels = (
                db.query(StudyPlanLevel)
                .filter(StudyPlanLevel.plan_id == plan.id)
                .order_by(StudyPlanLevel.level_index.asc())
                .all()
            )
            level_ids = [item.id for item in levels]
            classes: list[StudyPlanUnit] = []
            if level_ids:
                classes = (
                    db.query(StudyPlanUnit)
                    .filter(StudyPlanUnit.level_id.in_(level_ids))
                    .order_by(StudyPlanUnit.unit_index.asc())
                    .all()
                )
            total_classes = len(classes)
            completed_classes = sum(1 for c in classes if bool(c.is_completed))
            completed_recent = sum(
                1 for c in classes if c.completed_at is not None and c.completed_at.date() >= week_start
            )

            level_to_classes: dict[int, list[StudyPlanUnit]] = {}
            for item in classes:
                level_to_classes.setdefault(item.level_id, []).append(item)

            for level in levels:
                level_classes = level_to_classes.get(level.id, [])
                if not level_classes:
                    continue
                done = sum(1 for c in level_classes if bool(c.is_completed))
                if done < len(level_classes):
                    current_level = {
                        'id': level.id,
                        'title': level.title,
                        'level_index': level.level_index,
                        'completion_rate': round(done / max(1, len(level_classes)), 4),
                    }
                    break
            if current_level is None and levels:
                last_level = levels[-1]
                current_level = {
                    'id': last_level.id,
                    'title': last_level.title,
                    'level_index': last_level.level_index,
                    'completion_rate': 1.0,
                }

    completion_rate = 0.0 if total_classes == 0 else completed_classes / total_classes

    return {
        'streak_days': streak_days,
        'week_activity_days': week_activity_days,
        'week_interactions': week_interactions,
        'week_quizzes': week_quizzes,
        'active_language': (
            {
                'language_code': active_profile.language_code,
                'language_label': active_profile.language_label,
            }
            if active_profile
            else None
        ),
        'current_level': current_level,
        'plan_progress': {
            'total_classes': total_classes,
            'completed_classes': completed_classes,
            'completion_rate': round(completion_rate, 4),
            'completed_recent': completed_recent,
        },
        'milestones': {
            'total_conversations': len(
                db.query(ChatConversation)
                .filter(ChatConversation.user_id == current_user.id, ChatConversation.deleted_at.is_(None))
                .all()
            ),
            'total_interactions': len(logs),
        },
    }


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
