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


class QueryRequest(BaseModel):
    question: str = Field(min_length=2)


class QueryResponse(BaseModel):
    answer: str
    citations: list[dict]
    trace_id: str


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
