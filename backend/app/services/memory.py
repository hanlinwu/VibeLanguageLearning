import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.llm_client import llm_client
from app.models import LearningMemory, MemoryStreamChange, MemoryStreamItem

MAX_ACTIVE_MEMORIES = 80
FORCE_SAVE_MEMORY_KEYWORDS = ('保存到记忆流', '保存进记忆流', '记到记忆流')
LLM_MEMORY_EXTRACTOR_SYSTEM_PROMPT = (
    '你是长期记忆提炼器。请从一轮问答里提取“跨会话长期有价值”的学习信息，'
    '只输出 JSON 数组，不要输出任何解释。\n'
    '每个元素结构: '
    '{"category":"preference|progress|grammar|habit|goal",'
    '"memory_key":"stable-key",'
    '"content":"简短结论",'
    '"importance":0.0-1.0,'
    '"reason":"简短原因"}。\n'
    '规则: 只保留重要信息，最多 5 条；避免与短期上下文重复；memory_key 稳定可复用。'
)
LLM_FORCE_MEMORY_SUMMARY_SYSTEM_PROMPT = (
    '你是强制记忆总结器。用户明确要求“保存到记忆流”时，'
    '请将本轮问答总结为一个高价值长期记忆条目。'
    '只输出一个 JSON 对象，结构为: '
    '{"category":"manual|goal|preference|grammar|progress",'
    '"memory_key":"stable-key",'
    '"content":"简短总结",'
    '"importance":0.0-1.0,'
    '"reason":"explicit-save-request"}。'
)


def get_or_create_memory(db: Session, user_id: int) -> LearningMemory:
    memory = db.query(LearningMemory).filter(LearningMemory.user_id == user_id).first()
    if memory:
        return memory

    memory = LearningMemory(user_id=user_id, mastery={}, weak_points=[], last_difficulty=1)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def update_memory_with_quiz(db: Session, user_id: int, weak_points: list[str], score_ratio: float) -> LearningMemory:
    memory = get_or_create_memory(db, user_id)
    memory.weak_points = weak_points[:10]
    memory.last_difficulty = max(1, min(5, int(round(score_ratio * 5))))
    db.commit()
    db.refresh(memory)
    return memory


def _item_snapshot(item: MemoryStreamItem) -> dict:
    return {
        'id': item.id,
        'category': item.category,
        'memory_key': item.memory_key,
        'content': item.content,
        'importance': item.importance,
        'deleted_at': item.deleted_at.isoformat() if item.deleted_at else None,
    }


def _log_change(
    db: Session,
    user_id: int,
    item_id: Optional[int],
    action: str,
    reason: str,
    before_state: Optional[dict],
    after_state: Optional[dict],
    source_conversation_id: Optional[int],
    source_interaction_id: Optional[int],
) -> None:
    log = MemoryStreamChange(
        user_id=user_id,
        item_id=item_id,
        action=action,
        reason=reason[:200] if reason else None,
        before_state=before_state or {},
        after_state=after_state or {},
        source_conversation_id=source_conversation_id,
        source_interaction_id=source_interaction_id,
    )
    db.add(log)


def _upsert_memory_item(
    db: Session,
    user_id: int,
    category: str,
    memory_key: str,
    content: str,
    importance: float,
    reason: str,
    source_conversation_id: Optional[int],
    source_interaction_id: Optional[int],
) -> None:
    existing = (
        db.query(MemoryStreamItem)
        .filter(
            MemoryStreamItem.user_id == user_id,
            MemoryStreamItem.memory_key == memory_key,
            MemoryStreamItem.deleted_at.is_(None),
        )
        .first()
    )

    if existing is None:
        item = MemoryStreamItem(
            user_id=user_id,
            category=category,
            memory_key=memory_key,
            content=content,
            importance=importance,
            source_conversation_id=source_conversation_id,
            source_interaction_id=source_interaction_id,
        )
        db.add(item)
        db.flush()
        _log_change(
            db,
            user_id=user_id,
            item_id=item.id,
            action='create',
            reason=reason,
            before_state={},
            after_state=_item_snapshot(item),
            source_conversation_id=source_conversation_id,
            source_interaction_id=source_interaction_id,
        )
        return

    before = _item_snapshot(existing)
    if (
        existing.category == category
        and existing.content == content
        and abs(existing.importance - importance) < 1e-9
    ):
        return

    existing.category = category
    existing.content = content
    existing.importance = importance
    existing.source_conversation_id = source_conversation_id
    existing.source_interaction_id = source_interaction_id
    existing.updated_at = datetime.utcnow()
    db.add(existing)
    db.flush()
    _log_change(
        db,
        user_id=user_id,
        item_id=existing.id,
        action='update',
        reason=reason,
        before_state=before,
        after_state=_item_snapshot(existing),
        source_conversation_id=source_conversation_id,
        source_interaction_id=source_interaction_id,
    )


def _evict_if_needed(
    db: Session,
    user_id: int,
    source_conversation_id: Optional[int],
    source_interaction_id: Optional[int],
) -> None:
    active_items = (
        db.query(MemoryStreamItem)
        .filter(MemoryStreamItem.user_id == user_id, MemoryStreamItem.deleted_at.is_(None))
        .order_by(MemoryStreamItem.importance.asc(), MemoryStreamItem.updated_at.asc())
        .all()
    )
    if len(active_items) <= MAX_ACTIVE_MEMORIES:
        return

    overflow = len(active_items) - MAX_ACTIVE_MEMORIES
    for item in active_items[:overflow]:
        before = _item_snapshot(item)
        item.deleted_at = datetime.utcnow()
        db.add(item)
        db.flush()
        _log_change(
            db,
            user_id=user_id,
            item_id=item.id,
            action='delete',
            reason='memory-eviction',
            before_state=before,
            after_state=_item_snapshot(item),
            source_conversation_id=source_conversation_id,
            source_interaction_id=source_interaction_id,
        )


def _extract_json_array(text: str) -> list[dict]:
    raw = (text or '').strip()
    if not raw:
        return []
    if raw.startswith('```'):
        raw = raw.strip('`')
        if raw.startswith('json'):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find('[')
        end = raw.rfind(']')
        if start < 0 or end < start:
            return []
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _normalize_signal(item: dict) -> Optional[dict]:
    category = str(item.get('category') or '').strip().lower()
    memory_key = str(item.get('memory_key') or '').strip()
    content = str(item.get('content') or '').strip()
    reason = str(item.get('reason') or 'llm-extracted').strip()[:200]
    if not category or not memory_key or not content:
        return None
    try:
        importance = float(item.get('importance', 0.75))
    except (TypeError, ValueError):
        importance = 0.75
    importance = max(0.0, min(1.0, importance))
    return {
        'category': category,
        'memory_key': memory_key[:160],
        'content': content[:800],
        'importance': importance,
        'reason': reason,
    }


def _extract_important_signals(question: str, answer: str) -> list[dict]:
    user_prompt = (
        '请从下面这轮问答提炼长期记忆条目。\n'
        f'用户问题:\n{question}\n\n'
        f'助手回答:\n{answer}\n\n'
        '输出 JSON 数组。'
    )
    llm_text = llm_client.chat(LLM_MEMORY_EXTRACTOR_SYSTEM_PROMPT, user_prompt)
    raw_items = _extract_json_array(llm_text)
    normalized: list[dict] = []
    dedup: set[str] = set()
    for raw in raw_items:
        signal = _normalize_signal(raw)
        if signal is None:
            continue
        if signal['memory_key'] in dedup:
            continue
        dedup.add(signal['memory_key'])
        normalized.append(signal)
        if len(normalized) >= 5:
            break
    return normalized


def _should_force_save(question: str) -> bool:
    text = (question or '').strip()
    if not text:
        return False
    return any(keyword in text for keyword in FORCE_SAVE_MEMORY_KEYWORDS)


def _extract_force_signal(
    question: str,
    answer: str,
    source_interaction_id: int,
) -> Optional[dict]:
    user_prompt = (
        '用户明确要求保存到记忆流，请总结并输出一个 JSON 对象。\n'
        f'用户问题:\n{question}\n\n'
        f'助手回答:\n{answer}\n'
    )
    llm_text = llm_client.chat(LLM_FORCE_MEMORY_SUMMARY_SYSTEM_PROMPT, user_prompt)
    parsed = _extract_json_array(llm_text)
    signal: Optional[dict] = None
    if parsed:
        signal = _normalize_signal(parsed[0])
    else:
        try:
            obj = json.loads((llm_text or '').strip())
            if isinstance(obj, dict):
                signal = _normalize_signal(obj)
        except json.JSONDecodeError:
            signal = None

    if signal is None:
        fallback_content = (llm_text or '').strip()[:800] or (question.strip()[:800] if question else '用户请求保存记忆')
        signal = {
            'category': 'manual',
            'memory_key': f'manual:explicit:{source_interaction_id}',
            'content': fallback_content,
            'importance': 0.95,
            'reason': 'explicit-save-request',
        }
        return signal

    signal['memory_key'] = f"manual:explicit:{source_interaction_id}"
    signal['category'] = signal.get('category') or 'manual'
    signal['reason'] = 'explicit-save-request'
    signal['importance'] = max(float(signal.get('importance', 0.95)), 0.9)
    return signal


def apply_memory_from_interaction(
    db: Session,
    user_id: int,
    source_conversation_id: int,
    source_interaction_id: int,
    question: str,
    answer: str,
) -> None:
    signals: list[dict] = []
    try:
        signals = _extract_important_signals(question, answer)
    except Exception:
        signals = []

    if _should_force_save(question):
        try:
            force_signal = _extract_force_signal(
                question=question,
                answer=answer,
                source_interaction_id=source_interaction_id,
            )
            if force_signal is not None:
                signals.append(force_signal)
        except Exception:
            pass

    if not signals:
        return

    for sig in signals:
        _upsert_memory_item(
            db=db,
            user_id=user_id,
            category=sig['category'],
            memory_key=sig['memory_key'],
            content=sig['content'],
            importance=float(sig['importance']),
            reason=sig['reason'],
            source_conversation_id=source_conversation_id,
            source_interaction_id=source_interaction_id,
        )

    _evict_if_needed(
        db,
        user_id=user_id,
        source_conversation_id=source_conversation_id,
        source_interaction_id=source_interaction_id,
    )


def build_memory_system_prompt(db: Session, user_id: int) -> str:
    items = (
        db.query(MemoryStreamItem)
        .filter(MemoryStreamItem.user_id == user_id, MemoryStreamItem.deleted_at.is_(None))
        .order_by(MemoryStreamItem.updated_at.desc(), MemoryStreamItem.importance.desc())
        .all()
    )
    if not items:
        return ''
    lines = [f"- [{item.category}] {item.content}" for item in items]
    return '\n'.join(lines)


def list_memory_stream(db: Session, user_id: int, limit_changes: int = 200) -> dict:
    items = (
        db.query(MemoryStreamItem)
        .filter(MemoryStreamItem.user_id == user_id, MemoryStreamItem.deleted_at.is_(None))
        .order_by(MemoryStreamItem.importance.desc(), MemoryStreamItem.updated_at.desc())
        .all()
    )
    changes = (
        db.query(MemoryStreamChange)
        .filter(MemoryStreamChange.user_id == user_id)
        .order_by(MemoryStreamChange.created_at.desc())
        .limit(max(1, min(limit_changes, 500)))
        .all()
    )
    return {
        'items': items,
        'changes': changes,
    }


def update_memory_item(
    db: Session,
    user_id: int,
    item_id: int,
    content: Optional[str] = None,
    importance: Optional[float] = None,
    reason: str = 'manual-update',
) -> Optional[MemoryStreamItem]:
    item = (
        db.query(MemoryStreamItem)
        .filter(MemoryStreamItem.id == item_id, MemoryStreamItem.user_id == user_id, MemoryStreamItem.deleted_at.is_(None))
        .first()
    )
    if item is None:
        return None

    before = _item_snapshot(item)
    changed = False
    if content is not None and content.strip() and content.strip() != item.content:
        item.content = content.strip()
        changed = True
    if importance is not None:
        normalized = max(0.0, min(1.0, float(importance)))
        if abs(normalized - item.importance) > 1e-9:
            item.importance = normalized
            changed = True
    if not changed:
        return item

    item.updated_at = datetime.utcnow()
    db.add(item)
    db.flush()
    _log_change(
        db,
        user_id=user_id,
        item_id=item.id,
        action='update',
        reason=reason,
        before_state=before,
        after_state=_item_snapshot(item),
        source_conversation_id=item.source_conversation_id,
        source_interaction_id=item.source_interaction_id,
    )
    return item


def soft_delete_memory_item(
    db: Session,
    user_id: int,
    item_id: int,
    reason: str = 'manual-delete',
) -> bool:
    item = (
        db.query(MemoryStreamItem)
        .filter(MemoryStreamItem.id == item_id, MemoryStreamItem.user_id == user_id, MemoryStreamItem.deleted_at.is_(None))
        .first()
    )
    if item is None:
        return False
    before = _item_snapshot(item)
    item.deleted_at = datetime.utcnow()
    item.updated_at = datetime.utcnow()
    db.add(item)
    db.flush()
    _log_change(
        db,
        user_id=user_id,
        item_id=item.id,
        action='delete',
        reason=reason,
        before_state=before,
        after_state=_item_snapshot(item),
        source_conversation_id=item.source_conversation_id,
        source_interaction_id=item.source_interaction_id,
    )
    return True
