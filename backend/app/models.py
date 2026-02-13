from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    target_language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeDocument(Base):
    __tablename__ = 'knowledge_documents'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    knowledge_base_id: Mapped[Optional[int]] = mapped_column(ForeignKey('knowledge_bases.id'), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    raw_content: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default='queued')
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    processed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeChunk(Base):
    __tablename__ = 'knowledge_chunks'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey('knowledge_documents.id'), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    knowledge_point: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))


class KnowledgeBase(Base):
    __tablename__ = 'knowledge_bases'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(16), default='private')
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LearningMemory(Base):
    __tablename__ = 'learning_memory'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True, index=True)
    mastery: Mapped[dict] = mapped_column(JSON, default=dict)
    weak_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_difficulty: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MemoryStreamItem(Base):
    __tablename__ = 'memory_stream_items'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    category: Mapped[str] = mapped_column(String(32))
    memory_key: Mapped[str] = mapped_column(String(160), index=True)
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    source_conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('chat_conversations.id'), nullable=True, index=True
    )
    source_interaction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('interaction_logs.id'), nullable=True, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MemoryStreamChange(Base):
    __tablename__ = 'memory_stream_changes'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    item_id: Mapped[Optional[int]] = mapped_column(ForeignKey('memory_stream_items.id'), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    before_state: Mapped[dict] = mapped_column(JSON, default=dict)
    after_state: Mapped[dict] = mapped_column(JSON, default=dict)
    source_conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('chat_conversations.id'), nullable=True, index=True
    )
    source_interaction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('interaction_logs.id'), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class QuizAttempt(Base):
    __tablename__ = 'quiz_attempts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    questions: Mapped[list[dict]] = mapped_column(JSON)
    submitted_answers: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InteractionLog(Base):
    __tablename__ = 'interaction_logs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey('chat_conversations.id'), index=True, nullable=True
    )
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict]] = mapped_column(JSON)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatConversation(Base):
    __tablename__ = 'chat_conversations'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(120))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelProvider(Base):
    __tablename__ = 'model_providers'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(255))
    api_key: Mapped[str] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelConfig(Base):
    __tablename__ = 'model_configs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey('model_providers.id'), index=True)
    model_name: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(160))
    model_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemSetting(Base):
    __tablename__ = 'system_settings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setting_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    setting_value: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserLanguageProfile(Base):
    __tablename__ = 'user_language_profiles'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    language_code: Mapped[str] = mapped_column(String(24))
    language_label: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StudyPlan(Base):
    __tablename__ = 'study_plans'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    language_profile_id: Mapped[int] = mapped_column(ForeignKey('user_language_profiles.id'), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    questionnaire_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StudyPlanLevel(Base):
    __tablename__ = 'study_plan_levels'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('study_plans.id'), index=True)
    level_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    objective: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    generated_detail: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StudyPlanUnit(Base):
    __tablename__ = 'study_plan_units'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level_id: Mapped[int] = mapped_column(ForeignKey('study_plan_levels.id'), index=True)
    unit_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    assessment_pass_score: Mapped[float] = mapped_column(Float, default=0.7)
    last_assessment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClassAssessmentAttempt(Base):
    __tablename__ = 'class_assessment_attempts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    class_unit_id: Mapped[int] = mapped_column(ForeignKey('study_plan_units.id'), index=True)
    questions: Mapped[list[dict]] = mapped_column(JSON)
    submitted_answers: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
