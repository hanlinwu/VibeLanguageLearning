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

## Docker 一键部署（推荐）

1. 准备环境变量

```bash
cp /Users/hlwu/Documents/AILanguageLearn/.env.docker.example /Users/hlwu/Documents/AILanguageLearn/.env.docker
```

至少填写：
- `LLM_API_KEY`
- 可选 `ADMIN_EMAILS`（逗号分隔管理员邮箱）

2. 一键启动

```bash
docker compose --env-file /Users/hlwu/Documents/AILanguageLearn/.env.docker up -d --build
```

也可以直接：

```bash
/Users/hlwu/Documents/AILanguageLearn/scripts/docker-up.sh
```

如果拉取镜像超时（`failed to fetch anonymous token` / `i/o timeout`），请在
`/Users/hlwu/Documents/AILanguageLearn/.env.docker` 里替换镜像地址为你可访问的镜像源：

```env
PGVECTOR_IMAGE=...
PYTHON_BASE_IMAGE=...
NODE_BASE_IMAGE=...
NGINX_BASE_IMAGE=...
```

然后重试：

```bash
docker compose --env-file /Users/hlwu/Documents/AILanguageLearn/.env.docker build --no-cache
docker compose --env-file /Users/hlwu/Documents/AILanguageLearn/.env.docker up -d
```

3. 访问

- 前端（含 API 反向代理）：`http://localhost`
- 后端健康检查（容器内）：`http://localhost/api/health`

4. 停止

```bash
docker compose --env-file /Users/hlwu/Documents/AILanguageLearn/.env.docker down
```

或：

```bash
/Users/hlwu/Documents/AILanguageLearn/scripts/docker-down.sh
```

5. 数据持久化

- PostgreSQL 数据持久化在命名卷：`ailanguagelearn_pgdata`
- 删除容器后数据仍保留；仅执行以下命令才会清空数据：

```bash
docker compose --env-file /Users/hlwu/Documents/AILanguageLearn/.env.docker down -v
```

## 本地开发（非 Docker）

1. 启动数据库：`docker compose up -d db`
2. 启动后端：

```bash
cd /Users/hlwu/Documents/AILanguageLearn/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

3. 启动前端：

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
