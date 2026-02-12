# French Learning MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a full-loop MVP (RAG query + long-term memory + adaptive quiz) using Vue frontend, FastAPI backend, and PostgreSQL/pgvector.

**Architecture:** Use a modular FastAPI monolith with clear service layers (`auth`, `knowledge`, `query`, `quiz`, `memory`) and a separated Vue SPA frontend. Persist all user-facing history and state in PostgreSQL; use pgvector for chunk retrieval and feed retrieved context into LLM generation via OpenAI-compatible API.

**Tech Stack:** Vue 3 + TypeScript + Vite + Pinia, FastAPI + SQLAlchemy + Alembic-ready models, PostgreSQL + pgvector, pytest.

---

### Task 1: Project Scaffold

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`
- Create: `backend/app/db.py`
- Create: `backend/requirements.txt`
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `docker-compose.yml`

**Step 1: Write the failing test**
- Add `backend/tests/test_health.py` expecting `/health` returns `200` and `{ "status": "ok" }`.

**Step 2: Run test to verify it fails**
Run: `cd backend && pytest tests/test_health.py -q`
Expected: FAIL because app route does not exist.

**Step 3: Write minimal implementation**
- Implement FastAPI app with `/health` route.
- Add base config and DB settings.

**Step 4: Run test to verify it passes**
Run: `cd backend && pytest tests/test_health.py -q`
Expected: PASS.

**Step 5: Commit**
```bash
git add backend docker-compose.yml frontend/package.json frontend/vite.config.ts
git commit -m "feat: scaffold full-stack mvp"
```

### Task 2: Auth + User Profile

**Files:**
- Create: `backend/app/models.py`
- Create: `backend/app/schemas.py`
- Create: `backend/app/routers/auth.py`
- Create: `backend/app/security.py`
- Test: `backend/tests/test_auth.py`

**Step 1: Write the failing test**
- Test register/login/me workflow.

**Step 2: Run test to verify it fails**
Run: `cd backend && pytest tests/test_auth.py -q`
Expected: FAIL with missing endpoints.

**Step 3: Write minimal implementation**
- Implement registration and JWT login.
- Implement `/auth/me` protected endpoint.

**Step 4: Run test to verify it passes**
Run: `cd backend && pytest tests/test_auth.py -q`
Expected: PASS.

**Step 5: Commit**
```bash
git add backend/app backend/tests/test_auth.py
git commit -m "feat: add authentication and current user api"
```

### Task 3: Knowledge Upload + Chunking + Retrieval

**Files:**
- Create: `backend/app/routers/knowledge.py`
- Create: `backend/app/services/knowledge.py`
- Test: `backend/tests/test_knowledge_upload.py`

**Step 1: Write the failing test**
- Upload markdown/json and assert chunks are persisted.

**Step 2: Run test to verify it fails**
Run: `cd backend && pytest tests/test_knowledge_upload.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Parse file, chunk text, request embeddings via pluggable OpenAI-compatible client.
- Save document + chunks.

**Step 4: Run test to verify it passes**
Run: `cd backend && pytest tests/test_knowledge_upload.py -q`
Expected: PASS.

**Step 5: Commit**
```bash
git add backend/app backend/tests/test_knowledge_upload.py
git commit -m "feat: implement knowledge ingestion with chunk storage"
```

### Task 4: Query (RAG) + Interaction Logs + Memory Update

**Files:**
- Create: `backend/app/routers/query.py`
- Create: `backend/app/services/query.py`
- Create: `backend/app/services/memory.py`
- Test: `backend/tests/test_query_flow.py`

**Step 1: Write the failing test**
- Assert query endpoint returns answer + citations and writes logs.

**Step 2: Run test to verify it fails**
Run: `cd backend && pytest tests/test_query_flow.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Retrieve top chunks (vector similarity), call LLM, persist interaction log, upsert memory profile.

**Step 4: Run test to verify it passes**
Run: `cd backend && pytest tests/test_query_flow.py -q`
Expected: PASS.

**Step 5: Commit**
```bash
git add backend/app backend/tests/test_query_flow.py
git commit -m "feat: implement rag query with memory updates"
```

### Task 5: Adaptive Quiz Generation + Submit

**Files:**
- Create: `backend/app/routers/quiz.py`
- Create: `backend/app/services/quiz.py`
- Test: `backend/tests/test_quiz_flow.py`

**Step 1: Write the failing test**
- Generate mixed quiz (MCQ + fill-in), submit answers, verify scoring updates memory.

**Step 2: Run test to verify it fails**
Run: `cd backend && pytest tests/test_quiz_flow.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Use learner profile + weak topics + retrieved chunks to generate questions.
- Persist attempts and update memory mastery stats.

**Step 4: Run test to verify it passes**
Run: `cd backend && pytest tests/test_quiz_flow.py -q`
Expected: PASS.

**Step 5: Commit**
```bash
git add backend/app backend/tests/test_quiz_flow.py
git commit -m "feat: add adaptive quiz generation and grading"
```

### Task 6: Vue Frontend MVP Pages

**Files:**
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/views/LoginView.vue`
- Create: `frontend/src/views/DashboardView.vue`
- Create: `frontend/src/components/KnowledgeUpload.vue`
- Create: `frontend/src/components/QueryPanel.vue`
- Create: `frontend/src/components/QuizPanel.vue`
- Create: `frontend/src/components/MemoryPanel.vue`

**Step 1: Write the failing test**
- Add basic component test or route smoke check.

**Step 2: Run test to verify it fails**
Run: `cd frontend && npm test`
Expected: FAIL if route/components missing.

**Step 3: Write minimal implementation**
- Implement auth flow and dashboard tabs for all core backend capabilities.

**Step 4: Run test to verify it passes**
Run: `cd frontend && npm run build`
Expected: PASS build.

**Step 5: Commit**
```bash
git add frontend
git commit -m "feat: implement vue mvp workflow pages"
```

### Task 7: Verification & Docs

**Files:**
- Create: `README.md`
- Create: `backend/.env.example`
- Create: `frontend/.env.example`

**Step 1: Verify end-to-end manually**
Run:
- `docker compose up -d db`
- `cd backend && uvicorn app.main:app --reload`
- `cd frontend && npm run dev`

**Step 2: Run test suite**
Run: `cd backend && pytest -q`
Expected: all pass.

**Step 3: Validate feature checklist**
- Register/login
- Upload knowledge file
- Ask RAG question with citations
- Generate and submit quiz
- Check updated memory profile

**Step 4: Commit docs**
```bash
git add README.md backend/.env.example frontend/.env.example docs/plans/2026-02-12-french-learning-mvp.md
git commit -m "docs: add setup and verification guide"
```
