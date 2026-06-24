# TestPilot AI — CLAUDE.md

## Project Overview
TestPilot AI is a multi-agent automated test generation platform. It analyzes GitHub pull requests, generates unit/integration/API tests using LLM agents, executes tests in a Docker sandbox, self-repairs failures, and posts results back to GitHub via n8n.

## Architecture
- **Backend**: Python 3.11 + FastAPI (async)
- **Agent Orchestration**: LangGraph with parallel execution
- **LLM Provider**: Anthropic (two-model routing strategy)
- **Database**: PostgreSQL via asyncpg
- **Job Queue**: AWS SQS (LocalStack for local dev)
- **Artifact Storage**: AWS S3 (LocalStack for local dev)
- **Observability**: Langfuse — every LLM call is traced
- **Test Sandbox**: Docker container isolation
- **Webhooks/Notifications**: n8n

## Model Routing (STRICT — do not deviate)
| Agent | Model | Reason |
|-------|-------|--------|
| context_collector | claude-haiku-3-5 | structured extraction |
| risk_classifier | claude-haiku-3-5 | categorical output |
| test_strategist | claude-sonnet-4-5 | multi-step reasoning |
| test_generator | claude-sonnet-4-5 | code quality |
| failure_diagnoser | claude-sonnet-4-5 | log reasoning |
| pr_summarizer | claude-haiku-3-5 | summarization |

## Security Rules
- All credentials in `.env`. Never hardcode any keys.
- Use `python-dotenv` / `pydantic-settings` to load them.
- `.env` is gitignored. `.env.example` is the template.
- Validate GitHub webhook signatures on every incoming webhook.

## Code Standards
- **No placeholder comments** like "add logic here". Every function either works completely or raises `NotImplementedError("description")`.
- **Async throughout**: use `asyncpg`, `httpx`. Never use `requests` or `psycopg2`.
- **Pydantic v2** for all data models and settings.
- **Type hints** on every function signature.
- **Structured logging** with `loguru` — use `logger.info/debug/error` with `bind()` for context.
- **Retry logic**: exponential backoff, max 3 attempts, on all external calls.

## Directory Structure
```
testpilot-ai/
├── CLAUDE.md               ← this file
├── .env.example            ← credential template
├── .gitignore
├── requirements.txt
├── Dockerfile              ← API service image
├── docker-compose.yml      ← api + postgres + localstack
├── backend/
│   ├── main.py             ← FastAPI app, lifespan, all routes
│   ├── config.py           ← pydantic BaseSettings, fail-fast
│   ├── agents/
│   │   ├── base_agent.py   ← abstract base, Langfuse tracing, retry
│   │   ├── context_collector.py
│   │   ├── risk_classifier.py
│   │   ├── test_strategist.py
│   │   ├── test_generator.py
│   │   ├── failure_diagnostician.py
│   │   └── pr_summarizer.py
│   ├── graph/
│   │   ├── state.py        ← LangGraph TypedDict state
│   │   └── pipeline.py     ← graph definition, node wiring
│   ├── models/
│   │   └── schemas.py      ← Pydantic v2 models
│   ├── db/
│   │   └── connection.py   ← asyncpg pool, create_tables()
│   └── tools/
│       ├── github_client.py
│       ├── docker_runner.py
│       └── s3_client.py
├── seeder/
│   └── github_seeder.py    ← manual job injection for testing
├── sandbox/
│   └── Dockerfile          ← isolated test execution container
└── workflows/
    └── README.md           ← n8n workflow setup instructions
```

## Running Locally
```bash
# 1. Copy and fill environment
cp .env.example .env
# edit .env with your real keys

# 2. Start all services
docker-compose up --build

# 3. Verify health
curl http://localhost:8000/health

# 4. Seed a test job
python seeder/github_seeder.py
```

## Database Schema
Three tables managed by `backend/db/connection.py::create_tables()`:
- `jobs` — one row per PR analysis job
- `agent_traces` — one row per agent execution, with token counts and latency
- `generated_tests` — one row per generated test file, with pass/fail/coverage

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | /webhook/github | Receives n8n-forwarded PR events |
| POST | /jobs | Creates a job directly (for testing) |
| GET | /jobs/{job_id} | Full job status with traces |
| GET | /jobs | Recent jobs with pagination |
| GET | /health | Service health + DB connectivity |

## n8n Integration
See `workflows/README.md` for how to import the n8n workflow that:
1. Receives GitHub PR webhooks
2. Forwards them to `POST /webhook/github`
3. Polls `GET /jobs/{job_id}` for completion
4. Posts summary comment back to GitHub PR
