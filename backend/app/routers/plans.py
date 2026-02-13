import json
from collections import defaultdict
from datetime import datetime
from threading import Lock, Thread
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, text
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.llm_client import llm_client
from app.models import (
    ClassAssessmentAttempt,
    LearningMemory,
    StudyPlan,
    StudyPlanLevel,
    StudyPlanUnit,
    User,
    UserLanguageProfile,
)

router = APIRouter(prefix='/plans', tags=['plans'])

LANGUAGE_MAP: dict[str, str] = {
    'en': '英语',
    'fr': '法语',
    'ja': '日语',
}

_PLANS_SCHEMA_LOCK = Lock()
_PLANS_SCHEMA_READY: set[str] = set()


def _ensure_plans_schema(db: Session) -> None:
    bind = db.get_bind()
    if bind is None:
        return
    db_key = str(bind.url)
    with _PLANS_SCHEMA_LOCK:
        if db_key in _PLANS_SCHEMA_READY:
            return

    dialect = bind.dialect.name
    if dialect == 'postgresql':
        lock_id = 92634117
        db.execute(text('SELECT pg_advisory_lock(:lock_id)'), {'lock_id': lock_id})
        try:
            db.execute(text('ALTER TABLE study_plans ADD COLUMN IF NOT EXISTS questionnaire_json JSONB'))
            db.execute(text('ALTER TABLE study_plan_units ADD COLUMN IF NOT EXISTS is_completed BOOLEAN DEFAULT FALSE'))
            db.execute(text('ALTER TABLE study_plan_units ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP NULL'))
            db.execute(
                text(
                    'ALTER TABLE study_plan_units '
                    'ADD COLUMN IF NOT EXISTS assessment_pass_score DOUBLE PRECISION DEFAULT 0.7'
                )
            )
            db.execute(text('ALTER TABLE study_plan_units ADD COLUMN IF NOT EXISTS last_assessment_score DOUBLE PRECISION NULL'))
            db.execute(
                text(
                    'CREATE TABLE IF NOT EXISTS class_assessment_attempts ('
                    'id SERIAL PRIMARY KEY, '
                    'user_id INTEGER REFERENCES users(id), '
                    'class_unit_id INTEGER REFERENCES study_plan_units(id), '
                    'questions JSONB, '
                    'submitted_answers JSONB NULL, '
                    'score DOUBLE PRECISION NULL, '
                    'passed BOOLEAN DEFAULT FALSE, '
                    'created_at TIMESTAMP DEFAULT NOW(), '
                    'updated_at TIMESTAMP DEFAULT NOW()'
                    ')'
                )
            )
        finally:
            db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': lock_id})
    elif dialect == 'sqlite':
        sp_columns = db.execute(text("PRAGMA table_info('study_plans')")).fetchall()
        sp_column_names = {row[1] for row in sp_columns}
        if 'questionnaire_json' not in sp_column_names:
            db.execute(text('ALTER TABLE study_plans ADD COLUMN questionnaire_json TEXT'))

        spu_columns = db.execute(text("PRAGMA table_info('study_plan_units')")).fetchall()
        spu_column_names = {row[1] for row in spu_columns}
        if 'is_completed' not in spu_column_names:
            db.execute(text('ALTER TABLE study_plan_units ADD COLUMN is_completed INTEGER DEFAULT 0'))
        if 'completed_at' not in spu_column_names:
            db.execute(text('ALTER TABLE study_plan_units ADD COLUMN completed_at TEXT'))
        if 'assessment_pass_score' not in spu_column_names:
            db.execute(text('ALTER TABLE study_plan_units ADD COLUMN assessment_pass_score REAL DEFAULT 0.7'))
        if 'last_assessment_score' not in spu_column_names:
            db.execute(text('ALTER TABLE study_plan_units ADD COLUMN last_assessment_score REAL'))
    db.commit()
    _PLANS_SCHEMA_READY.add(db_key)


class LanguageProfileResponse(BaseModel):
    id: int
    language_code: str
    language_label: str
    is_active: bool


class ClassResponse(BaseModel):
    id: int
    class_index: int
    title: str
    description: Optional[str] = None
    content_json: Optional[dict[str, Any]] = None
    is_completed: bool = False
    completed_at: Optional[str] = None
    last_assessment_score: Optional[float] = None


class SectionResponse(BaseModel):
    section_index: int
    title: str
    classes: list[ClassResponse]


class LevelResponse(BaseModel):
    id: int
    level_index: int
    title: str
    objective: Optional[str] = None
    generated_detail: bool
    sections: list[SectionResponse]


class PlanResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: str
    generation: Optional[dict[str, Any]] = None
    levels: list[LevelResponse]


class PlanEnvelopeResponse(BaseModel):
    language: LanguageProfileResponse
    plan: PlanResponse


class PlanListItemResponse(BaseModel):
    id: int
    language_code: str
    language_label: str
    title: str
    status: str
    level_count: int
    generation: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str


class PlanListResponse(BaseModel):
    plans: list[PlanListItemResponse]


class LanguagesResponse(BaseModel):
    languages: list[LanguageProfileResponse]


class CurrentPlanResponse(BaseModel):
    language: Optional[LanguageProfileResponse] = None
    plan: Optional[PlanResponse] = None


class CreatePlanRequest(BaseModel):
    language_code: Literal['en', 'fr', 'ja']
    current_level: str = Field(min_length=1, max_length=40)
    self_assessment: str = Field(min_length=4, max_length=300)
    target_level: str = Field(min_length=1, max_length=20)
    target_duration_weeks: int = Field(ge=1, le=260)
    learning_experience: Optional[str] = Field(default=None, max_length=300)
    preferred_focus: Optional[str] = Field(default=None, max_length=200)


class LearnerQuestionnaire(BaseModel):
    current_level: str
    self_assessment: str
    target_level: str
    target_duration_weeks: int
    learning_experience: Optional[str] = None
    preferred_focus: Optional[str] = None


class AssessmentGenerateResponse(BaseModel):
    attempt_id: int
    pass_score: float
    questions: list[dict[str, Any]]


class AssessmentSubmitRequest(BaseModel):
    attempt_id: int
    answers: list[str]


class AssessmentSubmitResponse(BaseModel):
    score: float
    correct: int
    total: int
    passed: bool
    class_completed: bool


class AssessmentStartResponse(BaseModel):
    attempt_id: int
    pass_score: float
    total_questions: int
    question_index: int
    question: dict[str, Any]


class AssessmentStepRequest(BaseModel):
    attempt_id: int
    answer: str


class AssessmentStepResponse(BaseModel):
    done: bool
    total_questions: int
    question_index: int
    question: Optional[dict[str, Any]] = None
    score: Optional[float] = None
    passed: Optional[bool] = None
    class_completed: bool = False
    completed_class_count: int = 0


class GenerateNextLevelResponse(BaseModel):
    plan_id: int
    generated_level: Optional[LevelResponse] = None
    done: bool


class PlanGenerationStatusResponse(BaseModel):
    plan_id: int
    job_id: Optional[str] = None
    status: str
    generated_levels: int
    target_levels: int
    current_step: Optional[str] = None
    error: Optional[str] = None


PLAN_GENERATION_JOBS: dict[int, dict[str, Any]] = {}
PLAN_GENERATION_LOCK = Lock()
ASSESSMENT_TOTAL_QUESTIONS = 5


def _normalize_json_block(raw: str) -> Any:
    text = (raw or '').strip()
    if not text:
        raise ValueError('empty response')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    first_obj = text.find('{')
    last_obj = text.rfind('}')
    if first_obj != -1 and last_obj != -1 and first_obj < last_obj:
        return json.loads(text[first_obj : last_obj + 1])

    first_arr = text.find('[')
    last_arr = text.rfind(']')
    if first_arr != -1 and last_arr != -1 and first_arr < last_arr:
        return json.loads(text[first_arr : last_arr + 1])
    raise ValueError('response has no json block')


def _fallback_outline(language_label: str) -> dict[str, Any]:
    return {
        'title': f'{language_label}分级学习计划',
        'description': f'围绕{language_label}的听说读写能力，按关卡逐步推进。',
        'levels': [
            {
                'title': 'Level 1 · 入门沟通',
                'objective': '掌握高频表达，建立最基础沟通能力',
                'sections': [
                    {
                        'title': 'Section 1 · 生存表达',
                        'classes': [
                            {'title': '问候与自我介绍', 'description': '完成姓名、国籍、职业的简短自我介绍'},
                            {'title': '基础礼貌表达', 'description': '熟练使用感谢、道歉、请求等礼貌句式'},
                        ],
                    },
                    {
                        'title': 'Section 2 · 听辨与发音',
                        'classes': [
                            {'title': '核心音素辨识', 'description': '区分易混音并建立听辨稳定性'},
                            {'title': '句子重音与节奏', 'description': '在短句中读出自然重音和停顿'},
                        ],
                    },
                ],
            },
            {
                'title': 'Level 2 · 语法骨架',
                'objective': '能稳定构造常见陈述、疑问与否定句',
                'sections': [
                    {
                        'title': 'Section 1 · 句型构建',
                        'classes': [
                            {'title': '时态与人称基础', 'description': '掌握最常用时态的人称变化'},
                            {'title': '高频疑问句', 'description': '围绕时间、地点、原因进行提问与追问'},
                        ],
                    },
                    {
                        'title': 'Section 2 · 书面表达',
                        'classes': [
                            {'title': '短文组织', 'description': '写出结构清晰的 80-120 字短文'},
                            {'title': '纠错与改写', 'description': '识别常见错误并改写为自然表达'},
                        ],
                    },
                ],
            },
            {
                'title': 'Level 3 · 场景实战',
                'objective': '在真实场景中进行连续表达与任务完成',
                'sections': [
                    {
                        'title': 'Section 1 · 生活场景',
                        'classes': [
                            {'title': '出行与导航', 'description': '完成问路、购票、转乘等连续对话'},
                            {'title': '餐饮与购物', 'description': '围绕偏好、价格、比较做完整表达'},
                        ],
                    },
                    {
                        'title': 'Section 2 · 学业工作',
                        'classes': [
                            {'title': '会议与汇报', 'description': '做 2-3 分钟结构化口头汇报'},
                            {'title': '邮件与消息', 'description': '写作目标明确、语气得体的工作沟通文本'},
                        ],
                    },
                ],
            },
        ],
    }


def _normalize_outline(parsed: Any, language_label: str) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ValueError('outline must be object')
    raw_levels = parsed.get('levels')
    if not isinstance(raw_levels, list) or len(raw_levels) < 3:
        raise ValueError('insufficient levels')

    levels: list[dict[str, Any]] = []
    for raw_level in raw_levels[:8]:
        if not isinstance(raw_level, dict):
            continue
        level_title = str(raw_level.get('title') or '').strip()
        if not level_title:
            continue
        level_objective = str(raw_level.get('objective') or '').strip() or None

        raw_sections = raw_level.get('sections')
        if not isinstance(raw_sections, list) or len(raw_sections) == 0:
            continue

        sections: list[dict[str, Any]] = []
        for raw_section in raw_sections[:8]:
            if not isinstance(raw_section, dict):
                continue
            section_title = str(raw_section.get('title') or '').strip()
            if not section_title:
                continue

            raw_classes = raw_section.get('classes')
            if not isinstance(raw_classes, list) or len(raw_classes) == 0:
                continue

            classes: list[dict[str, str]] = []
            for raw_class in raw_classes[:12]:
                if not isinstance(raw_class, dict):
                    continue
                class_title = str(raw_class.get('title') or '').strip()
                class_desc = str(raw_class.get('description') or '').strip()
                if not class_title:
                    continue
                if not class_desc:
                    class_desc = '该课用于巩固本 section 的关键能力。'
                classes.append({'title': class_title, 'description': class_desc})

            if classes:
                sections.append({'title': section_title, 'classes': classes})

        if sections:
            levels.append({'title': level_title, 'objective': level_objective, 'sections': sections})

    if len(levels) < 3:
        raise ValueError('insufficient normalized levels')

    return {
        'title': str(parsed.get('title') or f'{language_label}分级学习计划').strip(),
        'description': str(parsed.get('description') or '').strip() or None,
        'levels': levels,
    }


def _generate_outline(language_code: str, language_label: str, questionnaire: LearnerQuestionnaire) -> dict[str, Any]:
    system_prompt = (
        '你是语言学习路径规划器。输出严格 JSON：'
        '{"title": string, "description": string, "levels": ['
        '{"title": string, "objective": string, "sections": ['
        '{"title": string, "classes": [{"title": string, "description": string}]}'
        ']}'
        ']}。'
        '要求：4-6个level；每个level 2-3个section；每个section 2-4个class；'
        'class.description 要简短具体，便于后续自动生成内容。不要输出Markdown。'
    )
    user_prompt = (
        f'目标语言: {language_label}({language_code})\n'
        f'当前水平: {questionnaire.current_level}\n'
        f'自评: {questionnaire.self_assessment}\n'
        f'目标水平: {questionnaire.target_level}\n'
        f'计划时长(周): {questionnaire.target_duration_weeks}\n'
        f'学习经历: {questionnaire.learning_experience or ""}\n'
        f'偏好重点: {questionnaire.preferred_focus or ""}\n'
        '请据此生成完整计划。'
    )
    try:
        raw = llm_client.chat(system_prompt, user_prompt)
        parsed = _normalize_json_block(raw)
        return _normalize_outline(parsed, language_label)
    except Exception:
        return _fallback_outline(language_label)


def _fallback_class_details(language_label: str, class_title: str, class_desc: str) -> dict[str, Any]:
    return {
        'learning_goal': class_desc,
        'core_points': [
            f'{class_title} 的关键表达与结构',
            '识别常见错误并纠正',
            '在真实语境中输出 3-5 句完整表达',
        ],
        'practice': [
            f'{language_label} 跟读与复述',
            '填空与改写训练',
            '场景化微对话任务',
        ],
        'deliverable': '完成一段可复用的口语或书面表达样例',
    }


def _generate_class_details(
    language_label: str,
    level_title: str,
    level_objective: str,
    section_title: str,
    class_title: str,
    class_desc: str,
) -> dict[str, Any]:
    system_prompt = (
        '你是课程设计助手。请输出严格 JSON 对象：'
        '{"learning_goal": string, "core_points": [string], "practice": [string], "deliverable": string}。'
        '内容要和 class 的标题与描述一致，简洁可执行。'
    )
    user_prompt = (
        f'语言: {language_label}\n'
        f'level: {level_title}\n'
        f'level目标: {level_objective}\n'
        f'section: {section_title}\n'
        f'class: {class_title}\n'
        f'class简介: {class_desc}'
    )
    try:
        raw = llm_client.chat(system_prompt, user_prompt)
        parsed = _normalize_json_block(raw)
        if not isinstance(parsed, dict):
            raise ValueError('invalid class detail json')
        learning_goal = str(parsed.get('learning_goal') or '').strip()
        core_points = parsed.get('core_points')
        practice = parsed.get('practice')
        deliverable = str(parsed.get('deliverable') or '').strip()
        if not learning_goal or not isinstance(core_points, list) or not isinstance(practice, list):
            raise ValueError('missing fields')
        return {
            'learning_goal': learning_goal,
            'core_points': [str(item) for item in core_points[:6]],
            'practice': [str(item) for item in practice[:6]],
            'deliverable': deliverable or '完成本课输出任务',
        }
    except Exception:
        return _fallback_class_details(language_label, class_title, class_desc)


def _build_learner_profile_text(db: Session, user_id: int, questionnaire: Optional[dict[str, Any]]) -> str:
    memory = db.query(LearningMemory).filter(LearningMemory.user_id == user_id).first()
    weak_points = memory.weak_points if memory and isinstance(memory.weak_points, list) else []
    mastery = memory.mastery if memory and isinstance(memory.mastery, dict) else {}
    parts = [
        f'当前弱项: {", ".join(str(x) for x in weak_points[:6]) if weak_points else "暂无"}',
        f'掌握画像: {json.dumps(mastery, ensure_ascii=False)[:280] if mastery else "暂无"}',
    ]
    if isinstance(questionnaire, dict):
        parts.append(f'计划问卷: {json.dumps(questionnaire, ensure_ascii=False)[:360]}')
    return '\n'.join(parts)


def _fallback_assessment_questions(class_title: str, class_desc: str) -> list[dict[str, Any]]:
    return [
        {
            'type': 'choice',
            'prompt': f'关于「{class_title}」，下列哪项最符合该课目标？',
            'options': ['记忆无关词表', class_desc, '只做阅读不输出', '仅背诵语法术语'],
            'answer': 'B',
            'explanation': '该课目标应与 class 描述一致。',
        },
        {
            'type': 'fill_blank',
            'prompt': f'请补全：本课重点是____（答案请填“{class_title}”）',
            'answer': class_title,
            'explanation': '用于检测是否理解本课主题。',
        },
        {
            'type': 'judge',
            'prompt': f'判断正误：{class_desc}（回答 true 或 false）',
            'answer': 'true',
            'explanation': '用于确认学习者对目标理解正确。',
        },
    ]


def _normalize_assessment_questions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw[:10]:
        if not isinstance(item, dict):
            continue
        qtype = str(item.get('type') or '').strip().lower()
        prompt = str(item.get('prompt') or '').strip()
        answer = str(item.get('answer') or '').strip()
        if not qtype or not prompt or not answer:
            continue
        question: dict[str, Any] = {'type': qtype, 'prompt': prompt, 'answer': answer}
        options = item.get('options')
        if isinstance(options, list):
            question['options'] = [str(x) for x in options[:8]]
        explanation = str(item.get('explanation') or '').strip()
        if explanation:
            question['explanation'] = explanation
        normalized.append(question)
    return normalized


def _normalize_single_assessment_question(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    qtype = str(raw.get('type') or '').strip().lower()
    prompt = str(raw.get('prompt') or '').strip()
    if not qtype or not prompt:
        return None
    question: dict[str, Any] = {'type': qtype, 'prompt': prompt}
    options = raw.get('options')
    if isinstance(options, list):
        question['options'] = [str(x) for x in options[:8]]
    rubric = str(raw.get('rubric') or '').strip()
    if rubric:
        question['rubric'] = rubric
    return question


def _generate_single_assessment_question(
    db: Session,
    user_id: int,
    class_title: str,
    class_desc: str,
    class_detail: Optional[dict[str, Any]],
    questionnaire: Optional[dict[str, Any]],
    asked_questions: list[dict[str, Any]],
) -> dict[str, Any]:
    system_prompt = (
        '你是课程测评出题器。请输出一个严格 JSON 对象：'
        '{"type":"choice|fill_blank|judge","prompt":string,"options":[string],"rubric":string}。'
        '只出 1 道题；与已出题不重复；题目必须可明确判定对错。不要 markdown。'
    )
    user_prompt = (
        f'Class标题: {class_title}\n'
        f'Class描述: {class_desc}\n'
        f'Class详细内容: {json.dumps(class_detail or {}, ensure_ascii=False)}\n'
        f'学习者画像:\n{_build_learner_profile_text(db, user_id, questionnaire)}\n'
        f'已出题: {json.dumps(asked_questions or [], ensure_ascii=False)}'
    )
    try:
        raw = llm_client.chat(system_prompt, user_prompt)
        parsed = _normalize_json_block(raw)
        normalized = _normalize_single_assessment_question(parsed)
        if normalized:
            return normalized
    except Exception:
        pass

    fallback = _fallback_assessment_questions(class_title, class_desc)[0]
    return {
        'type': fallback.get('type', 'choice'),
        'prompt': fallback.get('prompt', f'关于「{class_title}」的一道基础题'),
        'options': fallback.get('options', []),
        'rubric': '根据题意判断是否与课程目标一致',
    }


def _evaluate_assessment_with_llm(
    class_title: str,
    class_desc: str,
    class_detail: Optional[dict[str, Any]],
    questions: list[dict[str, Any]],
    answers: list[str],
    pass_score: float,
) -> tuple[float, bool]:
    system_prompt = (
        '你是严格评分器。根据题目与用户答案评分。输出严格 JSON：'
        '{"score": number, "passed": boolean, "reason": string}。'
        'score 范围 0~1。不得输出 markdown。'
    )
    qa_rows: list[dict[str, Any]] = []
    for idx, q in enumerate(questions):
        qa_rows.append(
            {
                'index': idx + 1,
                'question': q,
                'answer': answers[idx] if idx < len(answers) else '',
            }
        )
    user_prompt = (
        f'Class标题: {class_title}\n'
        f'Class描述: {class_desc}\n'
        f'Class详细内容: {json.dumps(class_detail or {}, ensure_ascii=False)}\n'
        f'通过阈值: {pass_score}\n'
        f'作答记录: {json.dumps(qa_rows, ensure_ascii=False)}'
    )
    try:
        raw = llm_client.chat(system_prompt, user_prompt)
        parsed = _normalize_json_block(raw)
        if isinstance(parsed, dict):
            score = float(parsed.get('score') or 0.0)
            score = max(0.0, min(1.0, score))
            passed = bool(parsed.get('passed', score >= pass_score))
            return score, passed
    except Exception:
        pass

    non_empty = sum(1 for ans in answers if str(ans or '').strip())
    score = non_empty / max(1, len(questions))
    return score, score >= pass_score


def _mark_plan_until_class_completed(db: Session, user_id: int, class_id: int) -> int:
    row = (
        db.query(StudyPlanUnit, StudyPlanLevel, StudyPlan)
        .join(StudyPlanLevel, StudyPlanLevel.id == StudyPlanUnit.level_id)
        .join(StudyPlan, StudyPlan.id == StudyPlanLevel.plan_id)
        .filter(
            StudyPlanUnit.id == class_id,
            StudyPlan.user_id == user_id,
        )
        .first()
    )
    if row is None:
        return 0

    target_unit, target_level, target_plan = row
    units = (
        db.query(StudyPlanUnit, StudyPlanLevel)
        .join(StudyPlanLevel, StudyPlanLevel.id == StudyPlanUnit.level_id)
        .filter(StudyPlanLevel.plan_id == target_plan.id)
        .order_by(StudyPlanLevel.level_index.asc(), StudyPlanUnit.unit_index.asc(), StudyPlanUnit.id.asc())
        .all()
    )
    completed = 0
    for unit, level in units:
        before_or_equal = (
            level.level_index < target_level.level_index
            or (level.level_index == target_level.level_index and unit.unit_index <= target_unit.unit_index)
        )
        if not before_or_equal:
            continue
        if not unit.is_completed:
            unit.is_completed = True
            if unit.completed_at is None:
                unit.completed_at = datetime.utcnow()
            db.add(unit)
        completed += 1
    return completed


def _to_int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _infer_target_levels(duration_weeks: int) -> int:
    if duration_weeks <= 8:
        return 3
    if duration_weeks <= 16:
        return 4
    if duration_weeks <= 28:
        return 5
    return 6


def _get_generation_state(questionnaire_json: Optional[dict[str, Any]], duration_weeks: int) -> dict[str, Any]:
    q = questionnaire_json if isinstance(questionnaire_json, dict) else {}
    generation = q.get('generation') if isinstance(q.get('generation'), dict) else {}
    target_levels = _to_int_or_default(generation.get('target_levels'), _infer_target_levels(duration_weeks))
    generated_levels = _to_int_or_default(generation.get('generated_levels'), 0)
    return {
        'target_levels': max(3, min(8, target_levels)),
        'generated_levels': max(0, generated_levels),
        'is_complete': bool(generation.get('is_complete', False)),
    }


def _update_generation_state(questionnaire_json: dict[str, Any], generated_levels: int, target_levels: int) -> dict[str, Any]:
    q = dict(questionnaire_json or {})
    q['generation'] = {
        'target_levels': target_levels,
        'generated_levels': generated_levels,
        'is_complete': generated_levels >= target_levels,
    }
    return q


def _fallback_single_level(language_label: str, level_index: int) -> dict[str, Any]:
    fallback_levels = _fallback_outline(language_label).get('levels') or []
    idx = min(max(level_index - 1, 0), len(fallback_levels) - 1) if fallback_levels else 0
    if fallback_levels:
        return fallback_levels[idx]
    return {
        'title': f'Level {level_index} · 核心能力进阶',
        'objective': '围绕目标能力持续提升',
        'sections': [
            {
                'title': 'Section 1 · 核心表达',
                'classes': [
                    {'title': '高频表达', 'description': '掌握并应用核心表达结构'},
                    {'title': '结构化输出', 'description': '在真实场景中完成结构化表达'},
                ],
            }
        ],
    }


def _generate_single_level(
    language_code: str,
    language_label: str,
    questionnaire: dict[str, Any],
    existing_levels: list[dict[str, str]],
    next_level_index: int,
) -> dict[str, Any]:
    system_prompt = (
        '你是语言学习路径规划器。请只输出一个 level 的严格 JSON 对象：'
        '{"title": string, "objective": string, "sections": ['
        '{"title": string, "classes": [{"title": string, "description": string}]}'
        ']}。'
        '每个 level 2-3 个 section，每个 section 2-4 个 class。不要 markdown。'
    )
    user_prompt = (
        f'目标语言: {language_label}({language_code})\n'
        f'计划问卷: {json.dumps(questionnaire, ensure_ascii=False)}\n'
        f'已生成levels: {json.dumps(existing_levels, ensure_ascii=False)}\n'
        f'现在请生成第 {next_level_index} 个 level。'
    )
    try:
        raw = llm_client.chat(system_prompt, user_prompt)
        parsed = _normalize_json_block(raw)
        normalized = _normalize_outline(
            {'title': 'tmp', 'description': '', 'levels': [parsed, parsed, parsed]},
            language_label,
        )
        return normalized['levels'][0]
    except Exception:
        return _fallback_single_level(language_label, next_level_index)


def _generate_class_assessment_questions(
    db: Session,
    user_id: int,
    class_title: str,
    class_desc: str,
    class_detail: Optional[dict[str, Any]],
    questionnaire: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    system_prompt = (
        '你是课程测评设计器。请输出严格 JSON 数组，每项结构为'
        '{"type":"choice|fill_blank|judge","prompt":string,'
        '"options":[string](仅choice需要), "answer":string, "explanation":string}。'
        '题目必须可明确判分。输出 5 题。不要 markdown。'
    )
    user_prompt = (
        f'Class标题: {class_title}\n'
        f'Class描述: {class_desc}\n'
        f'Class详细内容: {json.dumps(class_detail or {}, ensure_ascii=False)}\n'
        f'学习者画像:\n{_build_learner_profile_text(db, user_id, questionnaire)}'
    )
    try:
        raw = llm_client.chat(system_prompt, user_prompt)
        parsed = _normalize_json_block(raw)
        questions = _normalize_assessment_questions(parsed)
        if len(questions) >= 3:
            return questions[:8]
    except Exception:
        pass
    return _fallback_assessment_questions(class_title, class_desc)


def _grade_assessment(questions: list[dict[str, Any]], answers: list[str]) -> tuple[int, int, float]:
    total = len(questions)
    if total == 0:
        return 0, 0, 0.0
    correct = 0
    for idx, q in enumerate(questions):
        expected = str(q.get('answer') or '').strip().lower()
        actual = str(answers[idx] if idx < len(answers) else '').strip().lower()
        if expected and actual == expected:
            correct += 1
    score = correct / total
    return correct, total, score


def _serialize_language(profile: UserLanguageProfile) -> LanguageProfileResponse:
    return LanguageProfileResponse(
        id=profile.id,
        language_code=profile.language_code,
        language_label=profile.language_label,
        is_active=bool(profile.is_active),
    )


def _serialize_level(level: StudyPlanLevel, units: list[StudyPlanUnit]) -> LevelResponse:
    by_section: dict[tuple[int, str], list[ClassResponse]] = defaultdict(list)

    ordered_units = sorted(units, key=lambda item: item.unit_index)
    for unit in ordered_units:
        meta = unit.content_json if isinstance(unit.content_json, dict) else {}
        section_index = _to_int_or_default(meta.get('section_index'), 1)
        section_title = str(meta.get('section_title') or 'Section 1 · 核心能力')
        class_index = _to_int_or_default(meta.get('class_index'), unit.unit_index)

        class_payload: Optional[dict[str, Any]] = None
        detail = meta.get('detail')
        if isinstance(detail, dict):
            class_payload = detail

        by_section[(section_index, section_title)].append(
            ClassResponse(
                id=unit.id,
                class_index=class_index,
                title=unit.title,
                description=unit.description,
                content_json=class_payload,
                is_completed=bool(unit.is_completed),
                completed_at=unit.completed_at.isoformat() if unit.completed_at else None,
                last_assessment_score=unit.last_assessment_score,
            )
        )

    sections: list[SectionResponse] = []
    for (section_index, section_title), classes in sorted(by_section.items(), key=lambda x: x[0][0]):
        sections.append(
            SectionResponse(
                section_index=section_index,
                title=section_title,
                classes=sorted(classes, key=lambda item: item.class_index),
            )
        )

    return LevelResponse(
        id=level.id,
        level_index=level.level_index,
        title=level.title,
        objective=level.objective,
        generated_detail=bool(level.generated_detail),
        sections=sections,
    )


def _serialize_plan(db: Session, plan: StudyPlan) -> PlanResponse:
    levels = (
        db.query(StudyPlanLevel)
        .filter(StudyPlanLevel.plan_id == plan.id)
        .order_by(StudyPlanLevel.level_index.asc(), StudyPlanLevel.id.asc())
        .all()
    )
    level_ids = [level.id for level in levels]
    units_by_level: dict[int, list[StudyPlanUnit]] = {level_id: [] for level_id in level_ids}
    if level_ids:
        units = (
            db.query(StudyPlanUnit)
            .filter(StudyPlanUnit.level_id.in_(level_ids))
            .order_by(StudyPlanUnit.unit_index.asc(), StudyPlanUnit.id.asc())
            .all()
        )
        for unit in units:
            units_by_level.setdefault(unit.level_id, []).append(unit)

    duration_weeks = _to_int_or_default(
        (plan.questionnaire_json or {}).get('target_duration_weeks') if isinstance(plan.questionnaire_json, dict) else 0,
        20,
    )
    generation = _get_generation_state(plan.questionnaire_json if isinstance(plan.questionnaire_json, dict) else {}, duration_weeks)
    generation['generated_levels'] = len(levels)
    generation['is_complete'] = len(levels) >= generation['target_levels']
    return PlanResponse(
        id=plan.id,
        title=plan.title,
        description=plan.description,
        status=plan.status,
        generation=generation,
        levels=[_serialize_level(level, units_by_level.get(level.id, [])) for level in levels],
    )


def _activate_language_profile(db: Session, user_id: int, profile_id: int) -> UserLanguageProfile:
    profiles = db.query(UserLanguageProfile).filter(UserLanguageProfile.user_id == user_id).all()
    selected: Optional[UserLanguageProfile] = None
    for profile in profiles:
        should_active = profile.id == profile_id
        if bool(profile.is_active) != should_active:
            profile.is_active = should_active
            db.add(profile)
        if should_active:
            selected = profile
    if selected is None:
        raise HTTPException(status_code=404, detail='Language profile not found')
    return selected


def _insert_level_skeleton(db: Session, plan_id: int, level_index: int, level: dict[str, Any]) -> LevelResponse:
    level_title = str(level.get('title') or '').strip() or f'Level {level_index}'
    level_objective = str(level.get('objective') or '').strip() or None
    level_row = StudyPlanLevel(
        plan_id=plan_id,
        level_index=level_index,
        title=level_title,
        objective=level_objective,
        generated_detail=False,
    )
    db.add(level_row)
    db.flush()

    unit_index = 0
    sections = level.get('sections') if isinstance(level.get('sections'), list) else []
    for section_idx, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            continue
        section_title = str(section.get('title') or '').strip() or f'Section {section_idx}'
        classes = section.get('classes') if isinstance(section.get('classes'), list) else []
        for class_idx, class_item in enumerate(classes, start=1):
            if not isinstance(class_item, dict):
                continue
            class_title = str(class_item.get('title') or '').strip()
            class_desc = str(class_item.get('description') or '').strip() or '该课用于巩固本 section 的关键能力。'
            if not class_title:
                continue
            unit_index += 1
            db.add(
                StudyPlanUnit(
                    level_id=level_row.id,
                    unit_index=unit_index,
                    title=class_title,
                    description=class_desc,
                    content_json={
                        'section_index': section_idx,
                        'section_title': section_title,
                        'class_index': class_idx,
                        'skeleton': True,
                    },
                )
            )

    db.flush()
    units = (
        db.query(StudyPlanUnit)
        .filter(StudyPlanUnit.level_id == level_row.id)
        .order_by(StudyPlanUnit.unit_index.asc())
        .all()
    )
    return _serialize_level(level_row, units)


def _get_plan_row(db: Session, user_id: int, plan_id: int) -> tuple[StudyPlan, UserLanguageProfile]:
    row = (
        db.query(StudyPlan, UserLanguageProfile)
        .join(UserLanguageProfile, UserLanguageProfile.id == StudyPlan.language_profile_id)
        .filter(StudyPlan.id == plan_id, StudyPlan.user_id == user_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Plan not found')
    return row


def _compute_generation_progress(db: Session, plan: StudyPlan) -> tuple[int, int]:
    questionnaire = plan.questionnaire_json if isinstance(plan.questionnaire_json, dict) else {}
    duration_weeks = _to_int_or_default(questionnaire.get('target_duration_weeks'), 20)
    generation = _get_generation_state(questionnaire, duration_weeks)
    generated_levels = (
        db.query(StudyPlanLevel)
        .filter(StudyPlanLevel.plan_id == plan.id)
        .count()
    )
    target_levels = generation['target_levels']
    return generated_levels, target_levels


def _build_generation_status(plan_id: int, status: str, generated_levels: int, target_levels: int, job_id: Optional[str] = None, current_step: Optional[str] = None, error: Optional[str] = None) -> PlanGenerationStatusResponse:
    return PlanGenerationStatusResponse(
        plan_id=plan_id,
        job_id=job_id,
        status=status,
        generated_levels=generated_levels,
        target_levels=target_levels,
        current_step=current_step,
        error=error,
    )


def _run_generation_worker(user_id: int, plan_id: int) -> None:
    db = SessionLocal()
    try:
        _ensure_plans_schema(db)
        while True:
            plan, _profile = _get_plan_row(db, user_id, plan_id)
            generated_levels, target_levels = _compute_generation_progress(db, plan)

            with PLAN_GENERATION_LOCK:
                job = PLAN_GENERATION_JOBS.get(plan_id)
                if not job:
                    return
                job['generated_levels'] = generated_levels
                job['target_levels'] = target_levels

            if generated_levels >= target_levels:
                with PLAN_GENERATION_LOCK:
                    job = PLAN_GENERATION_JOBS.get(plan_id)
                    if job:
                        job['status'] = 'completed'
                        job['current_step'] = '计划生成完成'
                return

            levels = (
                db.query(StudyPlanLevel)
                .filter(StudyPlanLevel.plan_id == plan.id)
                .order_by(StudyPlanLevel.level_index.asc())
                .all()
            )
            pending_level = next((lv for lv in levels if not lv.generated_detail), None)
            if pending_level is not None:
                with PLAN_GENERATION_LOCK:
                    job = PLAN_GENERATION_JOBS.get(plan_id)
                    if job:
                        job['current_step'] = f'生成 Level {pending_level.level_index} 详细内容'
                _ = _generate_level_content_impl(db, user_id, pending_level.id)
                db.expire_all()
                continue

            with PLAN_GENERATION_LOCK:
                job = PLAN_GENERATION_JOBS.get(plan_id)
                if job:
                    job['current_step'] = f'生成 Level {generated_levels + 1} 骨架'
            _ = _generate_next_level_impl(db, user_id, plan.id)
            db.expire_all()
    except Exception as exc:
        with PLAN_GENERATION_LOCK:
            job = PLAN_GENERATION_JOBS.get(plan_id)
            if job:
                job['status'] = 'failed'
                job['error'] = str(exc)[:400]
                job['current_step'] = None
    finally:
        db.close()


@router.post('/{plan_id}/generation/start', response_model=PlanGenerationStatusResponse)
def start_plan_generation(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanGenerationStatusResponse:
    _ensure_plans_schema(db)
    plan, _profile = _get_plan_row(db, current_user.id, plan_id)
    generated_levels, target_levels = _compute_generation_progress(db, plan)
    if generated_levels >= target_levels:
        return _build_generation_status(
            plan_id=plan_id,
            job_id=None,
            status='completed',
            generated_levels=generated_levels,
            target_levels=target_levels,
            current_step='计划生成完成',
        )

    with PLAN_GENERATION_LOCK:
        existing = PLAN_GENERATION_JOBS.get(plan_id)
        if existing and existing.get('status') == 'running':
            return _build_generation_status(
                plan_id=plan_id,
                job_id=existing.get('job_id'),
                status='running',
                generated_levels=int(existing.get('generated_levels') or generated_levels),
                target_levels=int(existing.get('target_levels') or target_levels),
                current_step=existing.get('current_step'),
                error=existing.get('error'),
            )

        job_id = uuid4().hex
        PLAN_GENERATION_JOBS[plan_id] = {
            'job_id': job_id,
            'status': 'running',
            'generated_levels': generated_levels,
            'target_levels': target_levels,
            'current_step': '任务已启动',
            'error': None,
            'user_id': current_user.id,
            'started_at': datetime.utcnow().isoformat(),
        }

    worker = Thread(target=_run_generation_worker, args=(current_user.id, plan_id), daemon=True)
    worker.start()

    return _build_generation_status(
        plan_id=plan_id,
        job_id=job_id,
        status='running',
        generated_levels=generated_levels,
        target_levels=target_levels,
        current_step='任务已启动',
    )


@router.get('/{plan_id}/generation/status', response_model=PlanGenerationStatusResponse)
def get_plan_generation_status(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanGenerationStatusResponse:
    _ensure_plans_schema(db)
    plan, _profile = _get_plan_row(db, current_user.id, plan_id)
    generated_levels, target_levels = _compute_generation_progress(db, plan)
    default_status = 'completed' if generated_levels >= target_levels else 'idle'
    default_step = '计划生成完成' if default_status == 'completed' else None

    with PLAN_GENERATION_LOCK:
        job = PLAN_GENERATION_JOBS.get(plan_id)
        if job and int(job.get('user_id') or 0) == current_user.id:
            job_status = str(job.get('status') or 'idle')
            if job_status == 'running':
                job['generated_levels'] = generated_levels
                job['target_levels'] = target_levels
                if generated_levels >= target_levels:
                    job['status'] = 'completed'
                    job['current_step'] = '计划生成完成'
                    job_status = 'completed'

            return _build_generation_status(
                plan_id=plan_id,
                job_id=job.get('job_id'),
                status=job_status,
                generated_levels=int(job.get('generated_levels') or generated_levels),
                target_levels=int(job.get('target_levels') or target_levels),
                current_step=job.get('current_step'),
                error=job.get('error'),
            )

    return _build_generation_status(
        plan_id=plan_id,
        job_id=None,
        status=default_status,
        generated_levels=generated_levels,
        target_levels=target_levels,
        current_step=default_step,
    )


@router.get('/languages', response_model=LanguagesResponse)
def list_languages(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LanguagesResponse:
    _ensure_plans_schema(db)
    profiles = (
        db.query(UserLanguageProfile)
        .join(StudyPlan, StudyPlan.language_profile_id == UserLanguageProfile.id)
        .filter(
            UserLanguageProfile.user_id == current_user.id,
            StudyPlan.user_id == current_user.id,
        )
        .distinct()
        .order_by(UserLanguageProfile.updated_at.desc(), UserLanguageProfile.created_at.desc())
        .all()
    )
    return LanguagesResponse(languages=[_serialize_language(profile) for profile in profiles])


@router.get('', response_model=PlanListResponse)
def list_plans(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanListResponse:
    _ensure_plans_schema(db)
    rows = (
        db.query(StudyPlan, UserLanguageProfile)
        .join(UserLanguageProfile, UserLanguageProfile.id == StudyPlan.language_profile_id)
        .filter(StudyPlan.user_id == current_user.id)
        .order_by(StudyPlan.updated_at.desc(), StudyPlan.created_at.desc())
        .all()
    )
    items: list[PlanListItemResponse] = []
    for plan, profile in rows:
        level_count = (
            db.query(StudyPlanLevel)
            .filter(StudyPlanLevel.plan_id == plan.id)
            .count()
        )
        duration_weeks = _to_int_or_default(
            (plan.questionnaire_json or {}).get('target_duration_weeks') if isinstance(plan.questionnaire_json, dict) else 0,
            20,
        )
        generation = _get_generation_state(plan.questionnaire_json if isinstance(plan.questionnaire_json, dict) else {}, duration_weeks)
        generation['generated_levels'] = level_count
        generation['is_complete'] = level_count >= generation['target_levels']
        items.append(
            PlanListItemResponse(
                id=plan.id,
                language_code=profile.language_code,
                language_label=profile.language_label,
                title=plan.title,
                status=plan.status,
                level_count=level_count,
                generation=generation,
                created_at=plan.created_at.isoformat(),
                updated_at=plan.updated_at.isoformat(),
            )
        )
    return PlanListResponse(plans=items)


@router.post('', response_model=PlanEnvelopeResponse, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: CreatePlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanEnvelopeResponse:
    _ensure_plans_schema(db)
    language_code = payload.language_code
    language_label = LANGUAGE_MAP.get(language_code)
    if not language_label:
        raise HTTPException(status_code=422, detail='Unsupported language')

    profile = (
        db.query(UserLanguageProfile)
        .filter(
            UserLanguageProfile.user_id == current_user.id,
            UserLanguageProfile.language_code == language_code,
        )
        .first()
    )
    if profile is None:
        profile = UserLanguageProfile(
            user_id=current_user.id,
            language_code=language_code,
            language_label=language_label,
            is_active=False,
        )
        db.add(profile)
        db.flush()

    _activate_language_profile(db, current_user.id, profile.id)

    db.query(StudyPlan).filter(StudyPlan.user_id == current_user.id, StudyPlan.status == 'active').update(
        {'status': 'inactive'}, synchronize_session=False
    )

    questionnaire = LearnerQuestionnaire(
        current_level=payload.current_level,
        self_assessment=payload.self_assessment,
        target_level=payload.target_level,
        target_duration_weeks=payload.target_duration_weeks,
        learning_experience=payload.learning_experience,
        preferred_focus=payload.preferred_focus,
    )

    questionnaire_json = _update_generation_state(
        questionnaire.model_dump(),
        generated_levels=0,
        target_levels=_infer_target_levels(payload.target_duration_weeks),
    )
    plan = StudyPlan(
        user_id=current_user.id,
        language_profile_id=profile.id,
        title=f'{language_label}学习计划（{datetime.utcnow().strftime("%m-%d %H:%M")}）',
        description=f'目标 {payload.target_level}，周期 {payload.target_duration_weeks} 周',
        questionnaire_json=questionnaire_json,
        status='active',
    )
    db.add(plan)
    db.flush()

    db.commit()
    db.refresh(profile)
    db.refresh(plan)
    return PlanEnvelopeResponse(language=_serialize_language(profile), plan=_serialize_plan(db, plan))


@router.patch('/languages/{language_profile_id}/activate', response_model=LanguageProfileResponse)
def activate_language(
    language_profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LanguageProfileResponse:
    _ensure_plans_schema(db)
    target = (
        db.query(UserLanguageProfile)
        .filter(
            UserLanguageProfile.id == language_profile_id,
            UserLanguageProfile.user_id == current_user.id,
        )
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail='Language profile not found')

    active = _activate_language_profile(db, current_user.id, target.id)
    db.commit()
    db.refresh(active)
    return _serialize_language(active)


@router.patch('/{plan_id}/activate', response_model=PlanEnvelopeResponse)
def activate_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlanEnvelopeResponse:
    _ensure_plans_schema(db)
    row = (
        db.query(StudyPlan, UserLanguageProfile)
        .join(UserLanguageProfile, UserLanguageProfile.id == StudyPlan.language_profile_id)
        .filter(StudyPlan.id == plan_id, StudyPlan.user_id == current_user.id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Plan not found')

    plan, profile = row
    db.query(StudyPlan).filter(StudyPlan.user_id == current_user.id, StudyPlan.status == 'active').update(
        {'status': 'inactive'}, synchronize_session=False
    )
    plan.status = 'active'
    db.add(plan)
    _activate_language_profile(db, current_user.id, profile.id)
    db.commit()
    db.refresh(plan)
    db.refresh(profile)
    return PlanEnvelopeResponse(language=_serialize_language(profile), plan=_serialize_plan(db, plan))


@router.delete('/{plan_id}')
def delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    _ensure_plans_schema(db)
    plan = db.query(StudyPlan).filter(StudyPlan.id == plan_id, StudyPlan.user_id == current_user.id).first()
    if plan is None:
        return {'deleted': False}

    levels = db.query(StudyPlanLevel).filter(StudyPlanLevel.plan_id == plan.id).all()
    level_ids = [item.id for item in levels]
    if level_ids:
        class_units = db.query(StudyPlanUnit).filter(StudyPlanUnit.level_id.in_(level_ids)).all()
        class_ids = [item.id for item in class_units]
        if class_ids:
            db.query(ClassAssessmentAttempt).filter(ClassAssessmentAttempt.class_unit_id.in_(class_ids)).delete(
                synchronize_session=False
            )
            db.query(StudyPlanUnit).filter(StudyPlanUnit.id.in_(class_ids)).delete(synchronize_session=False)
        db.query(StudyPlanLevel).filter(StudyPlanLevel.id.in_(level_ids)).delete(synchronize_session=False)
    db.delete(plan)
    db.commit()

    if plan.status == 'active':
        replacement = (
            db.query(StudyPlan)
            .filter(StudyPlan.user_id == current_user.id)
            .order_by(StudyPlan.updated_at.desc(), StudyPlan.created_at.desc())
            .first()
        )
        if replacement is not None:
            replacement.status = 'active'
            _activate_language_profile(db, current_user.id, replacement.language_profile_id)
            db.add(replacement)
            db.commit()
    return {'deleted': True}


@router.post('/{plan_id}/generate-next-level', response_model=GenerateNextLevelResponse)
def generate_next_level(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GenerateNextLevelResponse:
    _ensure_plans_schema(db)
    return _generate_next_level_impl(db, current_user.id, plan_id)

def _generate_next_level_impl(db: Session, user_id: int, plan_id: int) -> GenerateNextLevelResponse:
    row = (
        db.query(StudyPlan, UserLanguageProfile)
        .join(UserLanguageProfile, UserLanguageProfile.id == StudyPlan.language_profile_id)
        .filter(StudyPlan.id == plan_id, StudyPlan.user_id == user_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Plan not found')
    plan, profile = row

    questionnaire = plan.questionnaire_json if isinstance(plan.questionnaire_json, dict) else {}
    duration_weeks = _to_int_or_default(questionnaire.get('target_duration_weeks'), 20)
    generation = _get_generation_state(questionnaire, duration_weeks)
    existing_levels = (
        db.query(StudyPlanLevel)
        .filter(StudyPlanLevel.plan_id == plan.id)
        .order_by(StudyPlanLevel.level_index.asc())
        .all()
    )
    if len(existing_levels) >= generation['target_levels']:
        questionnaire = _update_generation_state(questionnaire, len(existing_levels), generation['target_levels'])
        plan.questionnaire_json = questionnaire
        db.add(plan)
        db.commit()
        return GenerateNextLevelResponse(plan_id=plan.id, generated_level=None, done=True)

    existing_outline = [{'title': item.title, 'objective': item.objective or ''} for item in existing_levels]
    next_level_index = len(existing_levels) + 1
    next_level = _generate_single_level(
        profile.language_code,
        profile.language_label,
        questionnaire,
        existing_outline,
        next_level_index,
    )
    serialized = _insert_level_skeleton(db, plan.id, next_level_index, next_level)
    questionnaire = _update_generation_state(questionnaire, next_level_index, generation['target_levels'])
    plan.questionnaire_json = questionnaire
    db.add(plan)
    db.commit()
    return GenerateNextLevelResponse(
        plan_id=plan.id,
        generated_level=serialized,
        done=bool(questionnaire['generation']['is_complete']),
    )


@router.get('/current', response_model=CurrentPlanResponse)
def get_current_plan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CurrentPlanResponse:
    _ensure_plans_schema(db)
    row = (
        db.query(StudyPlan, UserLanguageProfile)
        .join(UserLanguageProfile, UserLanguageProfile.id == StudyPlan.language_profile_id)
        .filter(StudyPlan.user_id == current_user.id, StudyPlan.status == 'active')
        .order_by(StudyPlan.updated_at.desc(), StudyPlan.created_at.desc())
        .first()
    )
    if row is None:
        return CurrentPlanResponse(language=None, plan=None)

    plan, profile = row
    return CurrentPlanResponse(language=_serialize_language(profile), plan=_serialize_plan(db, plan))


@router.post('/levels/{level_id}/generate-content', response_model=LevelResponse)
def generate_level_content(
    level_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LevelResponse:
    _ensure_plans_schema(db)
    return _generate_level_content_impl(db, current_user.id, level_id)


def _generate_level_content_impl(db: Session, user_id: int, level_id: int) -> LevelResponse:
    level_with_ctx = (
        db.query(StudyPlanLevel, StudyPlan, UserLanguageProfile)
        .join(StudyPlan, StudyPlan.id == StudyPlanLevel.plan_id)
        .join(UserLanguageProfile, UserLanguageProfile.id == StudyPlan.language_profile_id)
        .filter(
            StudyPlanLevel.id == level_id,
            StudyPlan.user_id == user_id,
            and_(UserLanguageProfile.user_id == user_id),
        )
        .first()
    )
    if level_with_ctx is None:
        raise HTTPException(status_code=404, detail='Level not found')

    level, _plan, language_profile = level_with_ctx

    units = (
        db.query(StudyPlanUnit)
        .filter(StudyPlanUnit.level_id == level.id)
        .order_by(StudyPlanUnit.unit_index.asc())
        .all()
    )
    if not units:
        raise HTTPException(status_code=400, detail='No class skeleton found for this level')

    for unit in units:
        raw_meta = unit.content_json if isinstance(unit.content_json, dict) else {}
        meta = dict(raw_meta)
        section_title = str(meta.get('section_title') or 'Section')
        detail = _generate_class_details(
            language_profile.language_label,
            level.title,
            level.objective or '',
            section_title,
            unit.title,
            unit.description or '',
        )
        meta['detail'] = detail
        meta['skeleton'] = False
        unit.content_json = meta
        db.add(unit)

    level.generated_detail = True
    db.add(level)
    db.commit()
    db.refresh(level)

    reloaded_units = (
        db.query(StudyPlanUnit)
        .filter(StudyPlanUnit.level_id == level.id)
        .order_by(StudyPlanUnit.unit_index.asc())
        .all()
    )
    return _serialize_level(level, reloaded_units)


@router.post('/classes/{class_id}/assessment/generate', response_model=AssessmentGenerateResponse)
def generate_class_assessment(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssessmentGenerateResponse:
    _ensure_plans_schema(db)
    row = (
        db.query(StudyPlanUnit, StudyPlanLevel, StudyPlan, UserLanguageProfile)
        .join(StudyPlanLevel, StudyPlanLevel.id == StudyPlanUnit.level_id)
        .join(StudyPlan, StudyPlan.id == StudyPlanLevel.plan_id)
        .join(UserLanguageProfile, UserLanguageProfile.id == StudyPlan.language_profile_id)
        .filter(
            StudyPlanUnit.id == class_id,
            StudyPlan.user_id == current_user.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Class not found')

    unit, _level, plan, _language = row
    meta = unit.content_json if isinstance(unit.content_json, dict) else {}
    class_detail = meta.get('detail') if isinstance(meta.get('detail'), dict) else None
    questions = _generate_class_assessment_questions(
        db,
        current_user.id,
        unit.title,
        unit.description or '',
        class_detail,
        plan.questionnaire_json if isinstance(plan.questionnaire_json, dict) else None,
    )
    attempt = ClassAssessmentAttempt(
        user_id=current_user.id,
        class_unit_id=unit.id,
        questions=questions,
        submitted_answers=None,
        score=None,
        passed=False,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return AssessmentGenerateResponse(
        attempt_id=attempt.id,
        pass_score=float(unit.assessment_pass_score or 0.7),
        questions=attempt.questions,
    )


@router.post('/classes/{class_id}/assessment/start', response_model=AssessmentStartResponse)
def start_class_assessment(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssessmentStartResponse:
    _ensure_plans_schema(db)
    row = (
        db.query(StudyPlanUnit, StudyPlan, UserLanguageProfile)
        .join(StudyPlanLevel, StudyPlanLevel.id == StudyPlanUnit.level_id)
        .join(StudyPlan, StudyPlan.id == StudyPlanLevel.plan_id)
        .join(UserLanguageProfile, UserLanguageProfile.id == StudyPlan.language_profile_id)
        .filter(
            StudyPlanUnit.id == class_id,
            StudyPlan.user_id == current_user.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Class not found')

    unit, plan, _language = row
    meta = unit.content_json if isinstance(unit.content_json, dict) else {}
    class_detail = meta.get('detail') if isinstance(meta.get('detail'), dict) else None
    first_question = _generate_single_assessment_question(
        db,
        current_user.id,
        unit.title,
        unit.description or '',
        class_detail,
        plan.questionnaire_json if isinstance(plan.questionnaire_json, dict) else None,
        asked_questions=[],
    )
    attempt = ClassAssessmentAttempt(
        user_id=current_user.id,
        class_unit_id=unit.id,
        questions=[first_question],
        submitted_answers=[],
        score=None,
        passed=False,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return AssessmentStartResponse(
        attempt_id=attempt.id,
        pass_score=float(unit.assessment_pass_score or 0.7),
        total_questions=ASSESSMENT_TOTAL_QUESTIONS,
        question_index=1,
        question=first_question,
    )


@router.post('/classes/{class_id}/assessment/step', response_model=AssessmentStepResponse)
def step_class_assessment(
    class_id: int,
    payload: AssessmentStepRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssessmentStepResponse:
    _ensure_plans_schema(db)
    row = (
        db.query(StudyPlanUnit, StudyPlan)
        .join(StudyPlanLevel, StudyPlanLevel.id == StudyPlanUnit.level_id)
        .join(StudyPlan, StudyPlan.id == StudyPlanLevel.plan_id)
        .filter(
            StudyPlanUnit.id == class_id,
            StudyPlan.user_id == current_user.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Class not found')
    unit, plan = row

    attempt = (
        db.query(ClassAssessmentAttempt)
        .filter(
            ClassAssessmentAttempt.id == payload.attempt_id,
            ClassAssessmentAttempt.user_id == current_user.id,
            ClassAssessmentAttempt.class_unit_id == class_id,
        )
        .first()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail='Assessment attempt not found')

    if attempt.score is not None:
        return AssessmentStepResponse(
            done=True,
            total_questions=ASSESSMENT_TOTAL_QUESTIONS,
            question_index=min(ASSESSMENT_TOTAL_QUESTIONS, len(attempt.questions or [])),
            question=None,
            score=float(attempt.score),
            passed=bool(attempt.passed),
            class_completed=bool(unit.is_completed),
            completed_class_count=0,
        )

    questions = list(attempt.questions or [])
    answers = list(attempt.submitted_answers or [])
    if not questions:
        raise HTTPException(status_code=400, detail='Assessment has no question')
    if len(answers) >= len(questions):
        raise HTTPException(status_code=400, detail='No pending question to answer')

    answers.append(payload.answer.strip())
    attempt.submitted_answers = answers

    pass_score = float(unit.assessment_pass_score or 0.7)
    meta = unit.content_json if isinstance(unit.content_json, dict) else {}
    class_detail = meta.get('detail') if isinstance(meta.get('detail'), dict) else None

    if len(answers) >= ASSESSMENT_TOTAL_QUESTIONS:
        score, passed = _evaluate_assessment_with_llm(
            unit.title,
            unit.description or '',
            class_detail,
            questions,
            answers,
            pass_score,
        )
        attempt.score = score
        attempt.passed = passed
        completed_count = 0
        if passed:
            unit.last_assessment_score = score
            completed_count = _mark_plan_until_class_completed(db, current_user.id, class_id)
        else:
            unit.last_assessment_score = score
            db.add(unit)
        db.add(attempt)
        db.commit()
        return AssessmentStepResponse(
            done=True,
            total_questions=ASSESSMENT_TOTAL_QUESTIONS,
            question_index=ASSESSMENT_TOTAL_QUESTIONS,
            question=None,
            score=score,
            passed=passed,
            class_completed=bool(unit.is_completed),
            completed_class_count=completed_count,
        )

    next_question = _generate_single_assessment_question(
        db,
        current_user.id,
        unit.title,
        unit.description or '',
        class_detail,
        plan.questionnaire_json if isinstance(plan.questionnaire_json, dict) else None,
        asked_questions=questions,
    )
    questions.append(next_question)
    attempt.questions = questions
    db.add(attempt)
    db.commit()
    return AssessmentStepResponse(
        done=False,
        total_questions=ASSESSMENT_TOTAL_QUESTIONS,
        question_index=len(questions),
        question=next_question,
        class_completed=bool(unit.is_completed),
    )


@router.post('/classes/{class_id}/assessment/submit', response_model=AssessmentSubmitResponse)
def submit_class_assessment(
    class_id: int,
    payload: AssessmentSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssessmentSubmitResponse:
    _ensure_plans_schema(db)
    unit = (
        db.query(StudyPlanUnit)
        .join(StudyPlanLevel, StudyPlanLevel.id == StudyPlanUnit.level_id)
        .join(StudyPlan, StudyPlan.id == StudyPlanLevel.plan_id)
        .filter(
            StudyPlanUnit.id == class_id,
            StudyPlan.user_id == current_user.id,
        )
        .first()
    )
    if unit is None:
        raise HTTPException(status_code=404, detail='Class not found')

    attempt = (
        db.query(ClassAssessmentAttempt)
        .filter(
            ClassAssessmentAttempt.id == payload.attempt_id,
            ClassAssessmentAttempt.user_id == current_user.id,
            ClassAssessmentAttempt.class_unit_id == class_id,
        )
        .first()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail='Assessment attempt not found')

    correct, total, score = _grade_assessment(attempt.questions or [], payload.answers)
    pass_score = float(unit.assessment_pass_score or 0.7)
    passed = score >= pass_score and total > 0

    attempt.submitted_answers = payload.answers
    attempt.score = score
    attempt.passed = passed
    db.add(attempt)

    unit.last_assessment_score = score
    if passed:
        unit.is_completed = True
        if unit.completed_at is None:
            unit.completed_at = datetime.utcnow()
    db.add(unit)
    db.commit()
    return AssessmentSubmitResponse(
        score=score,
        correct=correct,
        total=total,
        passed=passed,
        class_completed=bool(unit.is_completed),
    )
