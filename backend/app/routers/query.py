from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import QueryRequest, QueryResponse
from app.services.query import answer_question

router = APIRouter(prefix='/query', tags=['query'])


@router.post('', response_model=QueryResponse)
def query(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResponse:
    answer, citations, trace_id = answer_question(db, current_user.id, payload.question)
    return QueryResponse(answer=answer, citations=citations, trace_id=trace_id)
