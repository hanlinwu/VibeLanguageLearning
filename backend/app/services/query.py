import json
import uuid
import asyncio
import re
from collections.abc import Iterator
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm_client import llm_client
from app.models import (
    ChatConversation,
    InteractionLog,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    StudyPlan,
    StudyPlanLevel,
    StudyPlanUnit,
    UserLanguageProfile,
)
from app.services.model_registry import resolve_chat_model, resolve_default_embedding_model, resolve_web_search_settings
from app.services.memory import apply_memory_from_interaction, build_memory_system_prompt
from app.services.query_logic import rank_by_similarity
from app.services.web_search import search_web

BASE_SYSTEM_PROMPT = '你是语言学习助教。请结合最近对话保持上下文连续，并优先基于参考资料回答，保持简洁准确。'
settings = get_settings()
EXPLICIT_WEB_INTENT_PATTERNS = [
    r'联网搜索',
    r'上网(搜索|查)',
    r'网上(搜索|查)',
    r'搜索(网页|一下|下)',
    r'查(网页|官网|最新)',
    r'web\s*search',
    r'google\s*it',
]
WEB_NEED_PATTERNS = [
    r'最新|今天|近期|刚刚|新闻|公告|发布|更新|版本|价格|汇率|官网|政策|实时',
    r'\b(latest|today|news|release|update|price|official|docs?)\b',
]
WEB_SKIP_PATTERNS = [
    r'语法|翻译|改写|造句|练习|背单词|法语|发音|时态|变位',
    r'\b(grammar|translation|rewrite|exercise|vocab|conjugation)\b',
]


def retrieve_top_chunks(db: Session, user_id: int, question: str, top_k: int = 12) -> list[dict]:
    embedding_model = resolve_default_embedding_model(db)
    question_embedding = llm_client.embed_text_with_provider(
        question,
        embedding_model.base_url,
        embedding_model.api_key,
        embedding_model.model_name,
    )

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == 'postgresql':
        rows = (
            db.query(KnowledgeChunk, KnowledgeDocument, KnowledgeBase)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
            .filter(
                KnowledgeBase.is_enabled.is_(True),
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeDocument.embedding_model == embedding_model.model_name,
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
            KnowledgeDocument.deleted_at.is_(None),
            KnowledgeDocument.embedding_model == embedding_model.model_name,
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


def _has_pattern_match(question: str, patterns: list[str]) -> bool:
    text = (question or '').strip().lower()
    if not text:
        return False
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


def _has_explicit_web_intent(question: str) -> bool:
    return _has_pattern_match(question, EXPLICIT_WEB_INTENT_PATTERNS)


def _heuristic_need_web(question: str) -> bool:
    if _has_pattern_match(question, WEB_NEED_PATTERNS):
        return True
    if _has_pattern_match(question, WEB_SKIP_PATTERNS):
        return False
    # Questions with clear temporal cues should generally trigger web search.
    return bool(re.search(r'\b(20\d{2}|昨天|明天|上周|本周|今年)\b', question or '', flags=re.IGNORECASE))


def _llm_web_search_decision(question: str) -> Optional[bool]:
    messages = [
        {
            'role': 'system',
            'content': (
                '你是联网搜索决策器。只输出 YES 或 NO。'
                '若问题需要最新、外部事实、官网信息则输出 YES；'
                '若仅靠通用知识/语言教学即可回答则输出 NO。'
            ),
        },
        {'role': 'user', 'content': question},
    ]
    try:
        answer = llm_client.chat_messages(messages).strip().lower()
    except Exception:
        return None
    if answer.startswith('yes') or answer.startswith('是'):
        return True
    if answer.startswith('no') or answer.startswith('否'):
        return False
    return None


def _decide_should_search_web(db: Session, question: str, user_switch_enabled: bool) -> bool:
    if _has_explicit_web_intent(question):
        return True
    cfg = resolve_web_search_settings(db)
    if not cfg.enabled:
        return False
    if not user_switch_enabled:
        return False
    heuristic = _heuristic_need_web(question)
    llm_decision = _llm_web_search_decision(question)
    if llm_decision is not None:
        return llm_decision
    return heuristic


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
    web_context: str,
    active_plan_prompt: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{'role': 'system', 'content': BASE_SYSTEM_PROMPT}]
    if active_plan_prompt:
        messages.append({'role': 'system', 'content': active_plan_prompt})
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
    if web_context:
        messages.append(
            {
                'role': 'system',
                'content': (
                    '联网搜索摘要（可能有时效性，请结合引用谨慎使用）：\n'
                    f'{web_context}'
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


def _build_active_plan_system_prompt(db: Session, user_id: int) -> str:
    row = (
        db.query(StudyPlan, UserLanguageProfile)
        .join(UserLanguageProfile, UserLanguageProfile.id == StudyPlan.language_profile_id)
        .filter(StudyPlan.user_id == user_id, StudyPlan.status == 'active')
        .order_by(StudyPlan.updated_at.desc(), StudyPlan.created_at.desc())
        .first()
    )
    if row is None:
        return ''

    plan, language_profile = row
    levels = (
        db.query(StudyPlanLevel)
        .filter(StudyPlanLevel.plan_id == plan.id)
        .order_by(StudyPlanLevel.level_index.asc(), StudyPlanLevel.id.asc())
        .all()
    )
    level_ids = [item.id for item in levels]
    units_by_level: dict[int, list[StudyPlanUnit]] = {level_id: [] for level_id in level_ids}
    if level_ids:
        units = (
            db.query(StudyPlanUnit)
            .filter(StudyPlanUnit.level_id.in_(level_ids))
            .order_by(StudyPlanUnit.level_id.asc(), StudyPlanUnit.unit_index.asc(), StudyPlanUnit.id.asc())
            .all()
        )
        for unit in units:
            units_by_level.setdefault(unit.level_id, []).append(unit)

    lines: list[str] = [
        '当前激活学习计划（请将回答与此计划保持一致，并优先服务当前关卡目标）：',
        f'- 语言: {language_profile.language_label}',
        f'- 计划标题: {plan.title}',
        f'- 计划描述: {plan.description or "无"}',
        '- 计划结构:',
    ]
    if not levels:
        lines.append('  - 暂无 level（计划仍在生成）')
    for level in levels:
        lines.append(f'  - Level {level.level_index}: {level.title}')
        if level.objective:
            lines.append(f'    - 目标: {level.objective}')
        class_units = units_by_level.get(level.id, [])
        if not class_units:
            lines.append('    - 暂无 class')
            continue
        for unit in class_units:
            lines.append(f'    - Class {unit.unit_index}: {unit.title}')
            if unit.description:
                lines.append(f'      - 简述: {unit.description}')
            if isinstance(unit.content_json, dict):
                section_title = str(unit.content_json.get('section_title') or '').strip()
                class_index = unit.content_json.get('class_index')
                detail = unit.content_json.get('detail')
                if section_title:
                    if isinstance(class_index, int):
                        lines.append(f'      - Section: {section_title} (#{class_index})')
                    else:
                        lines.append(f'      - Section: {section_title}')
                if isinstance(detail, dict):
                    lines.append(f'      - 详细内容: {json.dumps(detail, ensure_ascii=False)}')
    return '\n'.join(lines)


def _build_web_context(web_results: list[dict]) -> str:
    if not web_results:
        return ''
    parts: list[str] = []
    for idx, item in enumerate(web_results, start=1):
        title = str(item.get('title') or f'Web result {idx}')
        snippet = str(item.get('snippet') or '').strip()
        url = str(item.get('url') or '').strip()
        if not snippet and not url:
            continue
        parts.append(f'[{idx}] {title}\n{snippet}\nURL: {url}')
    return '\n\n'.join(parts)


def _build_web_citations(web_results: list[dict]) -> list[dict]:
    citations: list[dict] = []
    for idx, item in enumerate(web_results, start=1):
        citations.append(
            {
                'chunk_id': -1000 - idx,
                'chunk_index': None,
                'preview': str(item.get('snippet') or '')[:220],
                'relevance_score': 0.0,
                'document_id': None,
                'document_filename': str(item.get('title') or f'联网结果 {idx}'),
                'knowledge_base_id': None,
                'knowledge_base_name': None,
                'source': 'web',
                'url': str(item.get('url') or ''),
                'source_name': str(item.get('source') or ''),
            }
        )
    return citations


def _build_web_no_result_citation() -> dict:
    return {
        'chunk_id': -1999,
        'chunk_index': None,
        'preview': '已尝试联网搜索，但未检索到可用网页结果（或当前网络不可达）。',
        'relevance_score': 0.0,
        'document_id': None,
        'document_filename': '联网搜索未命中',
        'knowledge_base_id': None,
        'knowledge_base_name': None,
        'source': 'web',
        'url': '',
        'source_name': 'web',
    }


def answer_question(
    db: Session,
    user_id: int,
    question: str,
    conversation_id: Optional[int] = None,
    use_memory_stream: bool = True,
    use_web_search: bool = False,
    chat_model_id: Optional[int] = None,
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
    should_search_web = _decide_should_search_web(db, question, use_web_search)
    web_results: list[dict] = []
    if should_search_web:
        try:
            web_results = search_web(db, question, max_results=4)
        except Exception:
            web_results = []
    web_context = _build_web_context(web_results)
    memory_prompt = ''
    if use_memory_stream:
        memory_prompt = build_memory_system_prompt(db, user_id)
    active_plan_prompt = _build_active_plan_system_prompt(db, user_id)
    messages = _build_chat_messages(recent_logs, question, relevant_candidates, memory_prompt, web_context, active_plan_prompt)
    resolved_chat_model = resolve_chat_model(db, chat_model_id)
    if resolved_chat_model is None:
        answer = llm_client.chat_messages(messages)
    else:
        answer = llm_client.chat_messages_with_provider(
            messages,
            resolved_chat_model.base_url,
            resolved_chat_model.api_key,
            resolved_chat_model.model_name,
        )

    web_citations = _build_web_citations(web_results)
    if should_search_web and not web_citations:
        web_citations = [_build_web_no_result_citation()]
    citations = _build_citations(relevant_candidates) + web_citations
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
    use_web_search: bool = False,
    chat_model_id: Optional[int] = None,
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
    should_search_web = _decide_should_search_web(db, question, use_web_search)
    web_results: list[dict] = []
    if should_search_web:
        try:
            web_results = search_web(db, question, max_results=4)
        except Exception:
            web_results = []
    web_context = _build_web_context(web_results)
    memory_prompt = ''
    if use_memory_stream:
        memory_prompt = build_memory_system_prompt(db, user_id)
    active_plan_prompt = _build_active_plan_system_prompt(db, user_id)
    messages = _build_chat_messages(recent_logs, question, relevant_candidates, memory_prompt, web_context, active_plan_prompt)
    web_citations = _build_web_citations(web_results)
    if should_search_web and not web_citations:
        web_citations = [_build_web_no_result_citation()]
    citations = _build_citations(relevant_candidates) + web_citations
    trace_id = uuid.uuid4().hex
    resolved_chat_model = resolve_chat_model(db, chat_model_id)

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
        if should_search_web:
            yield _event({'type': 'status', 'status': '正在联网搜索...', 'web_count': 0})
            if web_results:
                for idx in range(len(web_results)):
                    yield _event(
                        {
                            'type': 'status',
                            'status': f'正在解析网页 {idx + 1}/{len(web_results)}',
                            'web_count': idx + 1,
                        }
                    )
            else:
                yield _event({'type': 'status', 'status': '联网搜索未命中，改用知识库继续回答', 'web_count': 0})
        else:
            yield _event({'type': 'status', 'status': '正在思考回答...', 'web_count': 0})
        stream_iter = (
            llm_client.stream_chat_messages(messages)
            if resolved_chat_model is None
            else llm_client.stream_chat_messages_with_provider(
                messages,
                resolved_chat_model.base_url,
                resolved_chat_model.api_key,
                resolved_chat_model.model_name,
            )
        )
        for piece in stream_iter:
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
