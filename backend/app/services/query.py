import json
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.llm_client import llm_client
from app.models import ChatConversation, InteractionLog, KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.services.query_logic import format_recent_dialogue, rank_by_similarity


def retrieve_top_chunks(db: Session, user_id: int, question: str, top_k: int = 4) -> list[KnowledgeChunk]:
    question_embedding = llm_client.embed_text(question)

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == 'postgresql':
        return (
            db.query(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
            .filter(
                KnowledgeDocument.owner_id == user_id,
                KnowledgeBase.owner_id == user_id,
                KnowledgeBase.is_enabled.is_(True),
            )
            .order_by(KnowledgeChunk.embedding.cosine_distance(question_embedding))
            .limit(top_k)
            .all()
        )

    all_chunks = (
        db.query(KnowledgeChunk)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
        .filter(
            KnowledgeDocument.owner_id == user_id,
            KnowledgeBase.owner_id == user_id,
            KnowledgeBase.is_enabled.is_(True),
        )
        .all()
    )
    # sqlite returns numpy arrays for pgvector columns; normalize to lists for pure Python ranking.
    candidates = [{'chunk': chunk, 'embedding': list(chunk.embedding)} for chunk in all_chunks]
    ranked = rank_by_similarity(question_embedding, candidates, top_k=top_k)
    return [item['chunk'] for item in ranked]


def _build_conversation_title(question: str) -> str:
    cleaned = ' '.join(question.strip().split())
    if len(cleaned) <= 32:
        return cleaned or '新对话'
    return f'{cleaned[:32]}...'


def _get_or_create_conversation(
    db: Session, user_id: int, question: str, conversation_id: Optional[int] = None
) -> ChatConversation:
    if conversation_id is not None:
        conversation = (
            db.query(ChatConversation)
            .filter(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user_id,
                ChatConversation.deleted_at.is_(None),
            )
            .first()
        )
        if conversation is not None:
            return conversation

    conversation = ChatConversation(user_id=user_id, title=_build_conversation_title(question))
    db.add(conversation)
    db.flush()
    return conversation


def answer_question(
    db: Session, user_id: int, question: str, conversation_id: Optional[int] = None
) -> tuple[str, list[dict], str, int]:
    conversation = _get_or_create_conversation(db, user_id, question, conversation_id=conversation_id)
    recent_logs = (
        db.query(InteractionLog)
        .filter(
            InteractionLog.user_id == user_id,
            InteractionLog.conversation_id == conversation.id,
        )
        .order_by(InteractionLog.created_at.asc())
        .all()
    )
    recent_dialogue = format_recent_dialogue(
        [{'question': log.question, 'answer': log.answer} for log in recent_logs],
        max_turns=6,
    )
    dialogue_block = recent_dialogue if recent_dialogue else '(无)'

    chunks = retrieve_top_chunks(db, user_id, question)
    context = '\n\n'.join(chunk.text for chunk in chunks)
    prompt = (
        f'最近对话:\n{dialogue_block}\n\n'
        f'当前问题: {question}\n\n'
        f'参考资料:\n{context}'
    )
    answer = llm_client.chat(
        '你是法语学习助教。请结合最近对话保持上下文连续，并优先基于参考资料回答，保持简洁准确。',
        prompt,
    )

    citations = [{'chunk_id': c.id, 'preview': c.text[:120]} for c in chunks]
    trace_id = uuid.uuid4().hex

    log = InteractionLog(
        user_id=user_id,
        conversation_id=conversation.id,
        question=question,
        answer=answer,
        citations=citations,
        trace_id=trace_id,
    )
    conversation.updated_at = datetime.utcnow()
    db.add(log)
    db.commit()

    return answer, citations, trace_id, conversation.id


def stream_answer_question(
    db: Session, user_id: int, question: str, conversation_id: Optional[int] = None
) -> Iterator[str]:
    conversation = _get_or_create_conversation(db, user_id, question, conversation_id=conversation_id)
    recent_logs = (
        db.query(InteractionLog)
        .filter(
            InteractionLog.user_id == user_id,
            InteractionLog.conversation_id == conversation.id,
        )
        .order_by(InteractionLog.created_at.asc())
        .all()
    )
    recent_dialogue = format_recent_dialogue(
        [{'question': log.question, 'answer': log.answer} for log in recent_logs],
        max_turns=6,
    )
    dialogue_block = recent_dialogue if recent_dialogue else '(无)'

    chunks = retrieve_top_chunks(db, user_id, question)
    context = '\n\n'.join(chunk.text for chunk in chunks)
    prompt = (
        f'最近对话:\n{dialogue_block}\n\n'
        f'当前问题: {question}\n\n'
        f'参考资料:\n{context}'
    )
    citations = [{'chunk_id': c.id, 'preview': c.text[:120]} for c in chunks]
    trace_id = uuid.uuid4().hex

    def _event(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    answer_parts: list[str] = []
    finalized = False

    def _persist_and_done() -> str:
        answer = ''.join(answer_parts)
        log = InteractionLog(
            user_id=user_id,
            conversation_id=conversation.id,
            question=question,
            answer=answer,
            citations=citations,
            trace_id=trace_id,
        )
        conversation.updated_at = datetime.utcnow()
        db.add(log)
        db.commit()
        return _event(
            {
                'type': 'done',
                'trace_id': trace_id,
                'citations': citations,
                'conversation_id': conversation.id,
            }
        )

    try:
        yield _event(
            {
                'type': 'start',
                'trace_id': trace_id,
                'citations': citations,
                'conversation_id': conversation.id,
            }
        )
        for piece in llm_client.stream_chat(
            '你是法语学习助教。请结合最近对话保持上下文连续，并优先基于参考资料回答，保持简洁准确。',
            prompt,
        ):
            answer_parts.append(piece)
            yield _event({'type': 'chunk', 'content': piece})

        yield _persist_and_done()
        finalized = True
    except Exception as exc:  # pragma: no cover - runtime network issues
        if answer_parts:
            # When upstream stream is interrupted after partial content, persist
            # the partial answer so chat history remains available after refresh.
            try:
                yield _persist_and_done()
                finalized = True
            except Exception:
                db.rollback()
        yield _event({'type': 'error', 'message': str(exc)})
    finally:
        if not finalized:
            db.rollback()
