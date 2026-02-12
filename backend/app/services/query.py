import json
import uuid
import asyncio
from collections.abc import Iterator
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm_client import llm_client
from app.models import ChatConversation, InteractionLog, KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.services.memory import apply_memory_from_interaction, build_memory_system_prompt
from app.services.query_logic import rank_by_similarity

BASE_SYSTEM_PROMPT = '你是法语学习助教。请结合最近对话保持上下文连续，并优先基于参考资料回答，保持简洁准确。'
settings = get_settings()


def retrieve_top_chunks(db: Session, user_id: int, question: str, top_k: int = 12) -> list[dict]:
    question_embedding = llm_client.embed_text(question)

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == 'postgresql':
        rows = (
            db.query(KnowledgeChunk, KnowledgeDocument, KnowledgeBase)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
            .filter(
                KnowledgeBase.is_enabled.is_(True),
                or_(
                    KnowledgeBase.scope == 'public',
                    and_(KnowledgeBase.scope == 'private', KnowledgeBase.owner_id == user_id),
                ),
            )
            .order_by(KnowledgeChunk.embedding.cosine_distance(question_embedding))
            .limit(top_k)
            .all()
        )
        return [{'chunk': chunk, 'document': document, 'base': base} for chunk, document, base in rows]

    rows = (
        db.query(KnowledgeChunk, KnowledgeDocument, KnowledgeBase)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
        .filter(
            KnowledgeBase.is_enabled.is_(True),
            or_(
                KnowledgeBase.scope == 'public',
                and_(KnowledgeBase.scope == 'private', KnowledgeBase.owner_id == user_id),
            ),
        )
        .all()
    )
    all_candidates = [{'chunk': chunk, 'embedding': list(chunk.embedding), 'document': document, 'base': base} for chunk, document, base in rows]
    # sqlite returns numpy arrays for pgvector columns; normalize to lists for pure Python ranking.
    ranked = rank_by_similarity(question_embedding, all_candidates, top_k=top_k)
    return [{'chunk': item['chunk'], 'document': item['document'], 'base': item['base']} for item in ranked]


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


def _select_relevant_candidates(question: str, candidates: list[dict], top_k: int = 4) -> list[dict]:
    if not candidates:
        return []

    texts = [str(item['chunk'].text) for item in candidates]
    reranked = llm_client.rerank_texts(question, texts, top_k=len(candidates))
    rerank_enabled = bool(settings.llm_rerank_model.strip())
    idx_to_candidate = {idx: item for idx, item in enumerate(candidates)}

    picked: list[dict] = []
    for item in reranked:
        idx = item.get('index')
        score = item.get('score')
        if not isinstance(idx, int) or idx not in idx_to_candidate:
            continue
        if not isinstance(score, (int, float)):
            continue
        relevance_score = float(score)
        if relevance_score < settings.llm_rerank_min_score:
            continue
        candidate = idx_to_candidate[idx]
        picked.append(
            {
                'chunk': candidate['chunk'],
                'document': candidate['document'],
                'base': candidate['base'],
                'relevance_score': relevance_score,
            }
        )
    if picked:
        return picked[:top_k]

    if rerank_enabled:
        return []

    # Fallback when rerank is not configured: keep vector top recalls.
    fallback: list[dict] = []
    for idx, item in enumerate(candidates[:top_k]):
        fallback.append(
            {
                'chunk': item['chunk'],
                'document': item['document'],
                'base': item['base'],
                'relevance_score': max(0.01, 0.25 - idx * 0.03),
            }
        )
    return fallback


def _build_rag_context(candidates: list[dict]) -> str:
    if not candidates:
        return '(无)'
    return '\n\n'.join(
        (
            f"[chunk_id={item['chunk'].id}] "
            f"[doc={item['document'].filename}] "
            f"{item['chunk'].text}"
        )
        for item in candidates
    )


def _build_citations(candidates: list[dict]) -> list[dict]:
    citations: list[dict] = []
    for item in candidates:
        chunk = item['chunk']
        document = item['document']
        base = item['base']
        citations.append(
            {
                'chunk_id': chunk.id,
                'chunk_index': chunk.chunk_index,
                'preview': chunk.text[:160],
                'relevance_score': float(item.get('relevance_score', 0.0)),
                'document_id': document.id,
                'document_filename': document.filename,
                'knowledge_base_id': base.id,
                'knowledge_base_name': base.name,
            }
        )
    return citations


def _build_chat_messages(
    recent_logs: list[InteractionLog],
    question: str,
    candidates: list[dict],
    memory_prompt: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{'role': 'system', 'content': BASE_SYSTEM_PROMPT}]
    if memory_prompt:
        messages.append({'role': 'system', 'content': f'长期记忆（跨对话）:\n{memory_prompt}'})
    messages.append(
        {
            'role': 'system',
            'content': (
                '参考资料（RAG）如下，请优先依据这些内容回答；若资料不足，请明确说明：\n'
                f'{_build_rag_context(candidates)}'
            ),
        }
    )
    for log in recent_logs[-6:]:
        q = (log.question or '').strip()
        a = (log.answer or '').strip()
        if q:
            messages.append({'role': 'user', 'content': q})
        if a:
            messages.append({'role': 'assistant', 'content': a})
    messages.append({'role': 'user', 'content': question})
    return messages


def answer_question(
    db: Session,
    user_id: int,
    question: str,
    conversation_id: Optional[int] = None,
    use_memory_stream: bool = True,
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
    candidates = retrieve_top_chunks(db, user_id, question)
    relevant_candidates = _select_relevant_candidates(question, candidates, top_k=4)
    memory_prompt = ''
    if use_memory_stream:
        memory_prompt = build_memory_system_prompt(db, user_id)
    messages = _build_chat_messages(recent_logs, question, relevant_candidates, memory_prompt)
    answer = llm_client.chat_messages(messages)

    citations = _build_citations(relevant_candidates)
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
    db.flush()
    if use_memory_stream:
        apply_memory_from_interaction(
            db,
            user_id=user_id,
            source_conversation_id=conversation.id,
            source_interaction_id=log.id,
            question=question,
            answer=answer,
        )
    db.commit()

    return answer, citations, trace_id, conversation.id


def stream_answer_question(
    db: Session,
    user_id: int,
    question: str,
    conversation_id: Optional[int] = None,
    use_memory_stream: bool = True,
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
    candidates = retrieve_top_chunks(db, user_id, question)
    relevant_candidates = _select_relevant_candidates(question, candidates, top_k=4)
    memory_prompt = ''
    if use_memory_stream:
        memory_prompt = build_memory_system_prompt(db, user_id)
    messages = _build_chat_messages(recent_logs, question, relevant_candidates, memory_prompt)
    citations = _build_citations(relevant_candidates)
    trace_id = uuid.uuid4().hex

    def _event(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    answer_parts: list[str] = []
    finalized = False

    def _persist_answer(answer: str) -> None:
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
        db.flush()
        if use_memory_stream:
            apply_memory_from_interaction(
                db,
                user_id=user_id,
                source_conversation_id=conversation.id,
                source_interaction_id=log.id,
                question=question,
                answer=answer,
            )
        db.commit()

    def _persist_and_done() -> str:
        answer = ''.join(answer_parts)
        _persist_answer(answer)
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
        for piece in llm_client.stream_chat_messages(messages):
            answer_parts.append(piece)
            yield _event({'type': 'chunk', 'content': piece})

        yield _persist_and_done()
        finalized = True
    except (GeneratorExit, asyncio.CancelledError):
        # Client disconnected (e.g., clicked stop). Persist current state so
        # refresh can still show the stopped message in conversation history.
        try:
            _persist_answer(''.join(answer_parts))
            finalized = True
        except Exception:
            db.rollback()
        raise
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
