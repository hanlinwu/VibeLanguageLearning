# AI Language Learn MVP

Vue + FastAPI + PostgreSQL/pgvector 的法语学习系统 MVP。

## 功能

- 多用户注册登录
- 知识库文件上传（Markdown/JSON）并切片入库
- RAG 知识问答（返回引用片段）
- 自适应动态出题（选择题+填空题）
- 作答后更新学习记忆画像

## 目录

- `/Users/hlwu/Documents/AILanguageLearn/backend` FastAPI 后端
- `/Users/hlwu/Documents/AILanguageLearn/frontend` Vue 前端
- `/Users/hlwu/Documents/AILanguageLearn/docs/plans` 规划文档

## 本地启动

1. 启动数据库

```bash
docker compose up -d db
```

2. 启动后端

```bash
cd /Users/hlwu/Documents/AILanguageLearn/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

3. 启动前端

```bash
cd /Users/hlwu/Documents/AILanguageLearn/frontend
npm install
cp .env.example .env
npm run dev
```

## 关键数据表

- `users`
- `knowledge_documents`
- `knowledge_chunks`
- `interaction_logs`
- `learning_memory`
- `quiz_attempts`

每次对话会写入 `interaction_logs`，每次练习写入 `quiz_attempts`，并把聚合学习状态更新到 `learning_memory`。
