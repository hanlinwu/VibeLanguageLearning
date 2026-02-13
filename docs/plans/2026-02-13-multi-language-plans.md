# Multi-Language Study Plan Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split profile and study-plan logic so each user can manage multiple languages (one active), and generate Duolingo-style level/unit plans with LLM on demand.

**Architecture:** Add a dedicated `/plans` router on FastAPI using existing `UserLanguageProfile/StudyPlan/StudyPlanLevel/StudyPlanUnit` models. Keep personal center account-only. Rebuild Vue `PlanView` to show language cards at top and a level/unit plan timeline below, with unit content generated lazily by backend.

**Tech Stack:** FastAPI + SQLAlchemy + existing OpenAI-compatible `llm_client`, Vue3 + Element Plus + TypeScript.

---

### Task 1: Plans API contract and persistence
- Add plan schemas and `/plans` router.
- Support: list languages, create language plan (英语/法语/日语), activate one language, fetch active plan, lazy-generate level units.

### Task 2: LLM-backed plan generation
- Add JSON-generation helpers with robust fallback templates.
- Generate level outline on plan creation.
- Generate unit details only when requested by level.

### Task 3: Frontend plan page rebuild
- Replace plain target-language input with large language cards.
- New plan flow includes language chooser.
- Display multi-level learning roadmap and per-level “生成学习内容”.

### Task 4: Verification
- Add backend API tests for new flow.
- Run focused backend tests + frontend build.
