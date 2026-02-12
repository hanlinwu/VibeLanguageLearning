from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    display_name: str
    is_admin: bool = False


class QueryRequest(BaseModel):
    question: str = Field(min_length=2)
    conversation_id: Optional[int] = None
    use_memory_stream: bool = True


class QueryResponse(BaseModel):
    answer: str
    citations: list[dict]
    trace_id: str
    conversation_id: int


class QuizGenerateRequest(BaseModel):
    num_questions: int = Field(default=6, ge=2, le=20)


class QuizGenerateResponse(BaseModel):
    attempt_id: int
    questions: list[dict]


class QuizSubmitRequest(BaseModel):
    attempt_id: int
    answers: list[str]


class QuizSubmitResponse(BaseModel):
    score: float
    total: int
    correct: int


class MemoryResponse(BaseModel):
    mastery: dict
    weak_points: list[str]
    last_difficulty: int


class MemoryStreamItemResponse(BaseModel):
    id: int
    category: str
    memory_key: str
    content: str
    importance: float
    source_conversation_id: Optional[int] = None
    source_interaction_id: Optional[int] = None
    created_at: str
    updated_at: str


class MemoryStreamChangeResponse(BaseModel):
    id: int
    item_id: Optional[int] = None
    action: str
    reason: Optional[str] = None
    before_state: dict
    after_state: dict
    source_conversation_id: Optional[int] = None
    source_interaction_id: Optional[int] = None
    created_at: str


class MemoryStreamResponse(BaseModel):
    items: list[MemoryStreamItemResponse]
    changes: list[MemoryStreamChangeResponse]


class MemoryItemUpdateRequest(BaseModel):
    content: Optional[str] = None
    importance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason: Optional[str] = None
