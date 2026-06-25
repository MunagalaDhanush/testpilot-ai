# TestPilot AI

Production-grade multi-agent automated test generation platform for GitHub pull requests.

---

## Overview

TestPilot AI analyzes GitHub pull requests using a six-agent LangGraph pipeline, automatically
generates unit, integration, and API tests with Claude, executes them in isolated Docker
sandboxes, and self-repairs failures before surfacing results to a human reviewer. It is designed
for engineering teams that want continuous test coverage on every PR without slowing down their
review process.

The platform routes each task to the right model: lightweight extraction and classification work
runs on Claude Haiku 4.5, while multi-step reasoning and code generation runs on Claude Sonnet 4.6.
This dual-model strategy reduces per-job LLM cost by approximately 60% compared to running
everything through a single high-capability model, while preserving quality where it matters.

---

## Live Demo

```
[Dashboard Screenshot]
```

Built and deployed by Dhanush Munagala.

---

## What It Does

- Analyzes GitHub pull requests with six specialized AI agents that run in coordinated parallel phases
- Generates unit, integration, and API tests as pytest files, tailored to the risk profile of each PR
- Executes generated tests inside isolated Docker sandboxes to prevent interference with the host environment
- Self-repairs failing tests using a typed failure taxonomy — the diagnostician classifies each failure category and passes structured repair context back to the generator
- Routes tasks to the optimal Claude model: Haiku for structured extraction, Sonnet for reasoning and code generation
- Enforces a human-in-the-loop approval gate before any generated test suite is committed or posted to GitHub

---

## Architecture

### Agent Pipeline

| Agent | Model | Responsibility |
|---|---|---|
| `context_collector` | Claude Haiku 4.5 | Extracts changed files, functions, and diff context from the PR |
| `risk_classifier` | Claude Haiku 4.5 | Categorizes PR risk as low / medium / high / critical |
| `test_strategist` | Claude Sonnet 4.6 | Designs the test strategy: which test types, which modules, what edge cases |
| `test_generator` | Claude Sonnet 4.6 | Generates pytest files for unit, integration, and API test types in parallel |
| `failure_diagnoser` | Claude Sonnet 4.6 | Reads execution logs, classifies failures, produces structured repair instructions |
| `pr_summarizer` | Claude Haiku 4.5 | Produces a markdown summary of test results for the GitHub PR comment |

Phases 2 and 4 use `asyncio.gather` for parallel execution: the risk classifier and existing test
parser run simultaneously in Phase 2, and all three test generators run simultaneously in Phase 4,
cutting total pipeline time by approximately 3x compared to sequential execution.

### Model Routing Strategy

Claude Haiku 4.5 handles tasks with structured, predictable outputs: extracting file paths and
function names, classifying a PR into a risk tier, and formatting a markdown summary. These tasks
are high-volume and low-reasoning — Haiku completes them faster and at roughly 25x lower token cost
than Sonnet.

Claude Sonnet 4.6 handles tasks that require multi-step reasoning and code quality: designing a test
strategy that accounts for existing coverage, generating syntactically correct pytest files with
appropriate fixtures and mocks, and diagnosing ambiguous test failures. The quality difference on
these tasks is significant enough to justify the higher cost.

Combined, this routing strategy reduces cost per job by approximately 60% versus running all six
agents through Sonnet.

### Tech Stack

| Layer | Technologies |
|---|---|
| AI / ML | Anthropic API, Claude Haiku 4.5, Claude Sonnet 4.6, LangGraph |
| Backend | Python 3.11, FastAPI (async), asyncpg, Pydantic v2, loguru |
| Database | PostgreSQL 15 (AWS RDS in production, Docker in development) |
| Queue | AWS SQS (LocalStack 3.0 for local development) |
| Storage | AWS S3 (LocalStack for local development) |
| Test Sandbox | Docker container isolation, pytest, pytest-json-report |
| Orchestration | n8n (webhook intake and PR comment posting) |
| Observability | Langfuse (every LLM call traced), CloudWatch |
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, Recharts |
| Deployment | Docker Compose (local), AWS ECS / EC2 (production) |

---

## Key Features

**Parallel agent execution.** LangGraph orchestrates agents across six phases. Risk classification
and test-context parsing run concurrently in Phase 2. All three test generators (unit, integration,
API) run concurrently in Phase 4 via `asyncio.gather`. End-to-end pipeline time is approximately 3x
faster than a naive sequential implementation.

**Typed failure taxonomy.** When a generated test fails, the failure diagnoser does not simply
re-generate the test. It classifies the failure into categories (import error, fixture mismatch,
assertion logic, timeout, etc.) and produces structured repair instructions that the generator uses
on its next attempt. The repair loop runs up to three times before escalating to the human reviewer.

**Real-time dashboard.** The Next.js dashboard renders each agent's state — waiting, running,
completed, or failed — as a live pipeline visualization that polls every two seconds during active
jobs. Token counts, model labels, and latency are shown per agent.

**Human approval gate.** Before any test file is committed or any comment is posted to GitHub, a
human reviewer must approve or reject the generated suite from the dashboard. Approval triggers an
n8n workflow that posts the PR summary as a GitHub comment. Rejection discards the output.

**Embedded AI chatbot.** A floating chat interface in the dashboard provides contextual Q&A about
the active job or the platform architecture. The chatbot runs on Claude Haiku 4.5 via a Next.js API
route with a structured system prompt describing the TestPilot pipeline.

**Custom PR analysis.** The `/analyze` page accepts either a GitHub PR URL (auto-parses owner,
repo, and PR number) or a pasted raw diff, creates a job immediately, and redirects to the live
pipeline view.

**GitHub seeder.** The seeder script pulls recent merged PRs from configured repositories and
injects them as jobs, enabling historical analysis and pipeline validation without waiting for new
PR activity.

---

## Getting Started

### Prerequisites

- Docker Desktop
- Python 3.11 or later
- Node.js 20 or later
- Anthropic API key
- AWS account with SQS, S3, and RDS access (or LocalStack for local development)
- Langfuse account (cloud or self-hosted)
- n8n account (cloud or self-hosted)

### Environment Setup

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

The required variables are:

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# GitHub
GITHUB_TOKEN=ghp_...
GITHUB_WEBHOOK_SECRET=your-webhook-secret-here
GITHUB_REPOS=owner/repo,owner/repo2

# Langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# PostgreSQL
DATABASE_URL=postgresql://testpilot:testpilot@localhost:5432/testpilot

# AWS (use test/test with LocalStack for local development)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-2
AWS_ENDPOINT_URL=http://localhost:4566

# SQS
SQS_QUEUE_NAME=testpilot-jobs
SQS_QUEUE_URL=http://localhost:4566/000000000000/testpilot-jobs

# S3
S3_BUCKET_NAME=testpilot-artifacts

# App
APP_ENV=development
LOG_LEVEL=DEBUG
CORS_ORIGINS=http://localhost:3000,http://localhost:8000
```

### Running Locally

```bash
# 1. Clone the repository
git clone https://github.com/dhanushmunagala/testpilot-ai.git
cd testpilot-ai

# 2. Copy and fill the environment file
cp .env.example .env

# 3. Start all services (API, frontend, PostgreSQL, LocalStack)
docker compose up --build

# 4. Open the dashboard
open http://localhost:3000

# 5. Verify the API
curl http://localhost:8000/health
```

### Running the Seeder

To populate the queue with recent merged PRs from your configured repositories:

```bash
python seeder/github_seeder.py
```

Jobs will appear in the dashboard immediately and begin processing if the SQS consumer is active.

---

## Project Structure

```
testpilot-ai/
├── backend/
│   ├── main.py               FastAPI application, lifespan, all HTTP routes
│   ├── config.py             Pydantic BaseSettings with fail-fast validation
│   ├── job_processor.py      SQS consumer loop, pause/resume/stop/restart control
│   ├── agents/
│   │   ├── base_agent.py     Abstract base class with Langfuse tracing and retry logic
│   │   ├── context_collector.py
│   │   ├── risk_classifier.py
│   │   ├── test_strategist.py
│   │   ├── test_generator.py
│   │   ├── failure_diagnostician.py
│   │   └── pr_summarizer.py
│   ├── graph/
│   │   ├── state.py          LangGraph TypedDict state definition
│   │   └── pipeline.py       Graph assembly, parallel phases via asyncio.gather
│   ├── models/
│   │   └── schemas.py        All Pydantic v2 request and response models
│   ├── db/
│   │   └── connection.py     asyncpg pool initialization, table and index creation
│   └── tools/
│       ├── github_client.py  GitHub API integration
│       ├── docker_runner.py  Sandbox test execution
│       └── s3_client.py      Artifact upload and retrieval
├── frontend/
│   ├── app/
│   │   ├── page.tsx          Main dashboard: stats, jobs table, efficiency section, charts
│   │   ├── analyze/
│   │   │   └── page.tsx      Custom PR analysis form (URL or diff input)
│   │   ├── jobs/[id]/
│   │   │   └── page.tsx      Job detail: live pipeline view, test files, PR summary
│   │   └── api/chat/
│   │       └── route.ts      Next.js API route for the embedded chatbot
│   ├── components/
│   │   └── ChatBot.tsx       Floating chat drawer component
│   └── lib/
│       ├── api.ts            Typed fetch wrappers for all backend endpoints
│       └── types.ts          TypeScript interfaces mirroring the backend schemas
├── seeder/
│   └── github_seeder.py      CLI tool to inject merged PRs as jobs
├── sandbox/
│   └── Dockerfile            Isolated container image for test execution
├── workflows/
│   └── README.md             n8n workflow setup and import instructions
├── Dockerfile                API service container image
├── docker-compose.yml        Local development stack definition
├── requirements.txt          Python dependencies
└── .env.example              Environment variable template
```

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/webhook/github` | Receives n8n-forwarded GitHub PR webhook events |
| `POST` | `/jobs` | Creates a job directly (for testing) |
| `POST` | `/jobs/analyze` | Creates a job from a PR URL or raw diff |
| `GET` | `/jobs` | Lists recent jobs with pagination and stats |
| `GET` | `/jobs/{id}` | Full job detail with agent traces and generated tests |
| `POST` | `/jobs/{id}/approve` | Approves a job and triggers n8n PR comment |
| `POST` | `/jobs/{id}/reject` | Rejects a job and discards generated output |
| `GET` | `/analytics` | Aggregate metrics for charts |
| `GET` | `/system/status` | Consumer state, active and queued job counts |
| `POST` | `/system/pause` | Pauses the SQS consumer without losing queue position |
| `POST` | `/system/resume` | Resumes a paused consumer |
| `POST` | `/system/stop` | Permanently stops the consumer (requires restart) |
| `POST` | `/system/restart` | Resets stop/pause flags and spawns a new consumer task |
| `POST` | `/system/fetch-github` | Pulls recent merged PRs from configured repos |
| `GET` | `/health` | Service health and database connectivity |

---

## Resume Summary

Built TestPilot AI, a production-grade multi-agent test engineering platform using LangGraph,
FastAPI, and Claude's API with intelligent model routing — directing high-reasoning tasks to Claude
Sonnet 4.6 and high-volume extraction tasks to Claude Haiku 4.5, reducing per-job LLM cost by
approximately 60% versus single-model approaches. Implemented parallel agent execution via
`asyncio.gather` across a six-agent LangGraph pipeline, a typed failure taxonomy for self-repair
loops (up to three automated repair attempts before human escalation), Docker sandbox test execution,
and human-in-the-loop approval gates. Built full observability via Langfuse with per-call token
tracking and latency tracing. Features a Next.js 14 dashboard with real-time pipeline visualization
polling at 2-second intervals during active jobs, an embedded Claude Haiku AI chatbot for
contextual Q&A, and a custom PR analysis interface accepting GitHub URLs or raw diffs. Deployed with
AWS RDS (PostgreSQL), SQS for job queuing, S3 for artifact storage, and n8n for GitHub webhook
integration and PR comment automation.

---

## Built By

**Dhanush Munagala**
MS in Management Information Systems, University of Houston — 4.0 GPA, Dean's Award

[LinkedIn](https://linkedin.com/in/munagaladhanush) &nbsp;|&nbsp;
[Portfolio](https://munagaladhanush.github.io) &nbsp;|&nbsp;
[GitHub](https://github.com/MunagalaDhanush)

---

## License

MIT
