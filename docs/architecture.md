# TestPilot AI — System Architecture

```mermaid
graph TB
    subgraph ext["External"]
        GH["GitHub PR"]
        DEV["Developer"]
    end

    subgraph n8n_in["n8n (inbound)"]
        N8N_WH["Webhook Trigger\n(PR opened/synced)"]
    end

    subgraph api["FastAPI :8000"]
        WH["POST /webhook/github\n(sig validated)"]
        JOBS_EP["GET /jobs\nGET /jobs/{id}"]
        N8N_EP["POST /n8n/job-complete"]
    end

    subgraph queue["Job Queue"]
        SQS["AWS SQS\n(LocalStack dev)"]
        JP["Job Processor\n(SQS consumer)"]
    end

    subgraph pipeline["LangGraph Pipeline (parallel)"]
        CC["context_collector\nclaude-haiku-4-5-20251001"]
        RC["risk_classifier\nclaude-haiku-4-5-20251001"]
        TS["test_strategist\nclaude-sonnet-4-6"]
        TG1["test_generator (unit)\nclaude-sonnet-4-6"]
        TG2["test_generator (integration)\nclaude-sonnet-4-6"]
        TG3["test_generator (api)\nclaude-sonnet-4-6"]
        EXEC["Subprocess Test Runner\npytest --json-report"]
        FD["failure_diagnostician\nclaude-sonnet-4-6"]
        PS["pr_summarizer\nclaude-haiku-4-5-20251001"]
    end

    subgraph storage["Storage"]
        PG[("PostgreSQL\njobs · agent_traces\ngenerated_tests")]
        S3[("AWS S3\ntest artifacts")]
    end

    subgraph obs["Observability"]
        LF["Langfuse\ncloud.langfuse.com"]
    end

    subgraph n8n_out["n8n (outbound)"]
        N8N_COMMENT["GitHub Node\nPost PR comment"]
    end

    subgraph frontend["Next.js Dashboard :3000"]
        DASH["/ — Job list\n(auto-refresh 30s)"]
        DETAIL["/jobs/[id]\nTimeline · Chart · Tests"]
    end

    GH -->|"PR event"| N8N_WH
    N8N_WH -->|"POST /webhook/github"| WH
    WH -->|"enqueue"| SQS
    SQS -->|"poll"| JP
    JP -->|"ainvoke"| CC
    CC --> RC
    RC --> TS
    TS --> TG1 & TG2 & TG3
    TG1 & TG2 & TG3 --> EXEC
    EXEC -->|"failures?"| FD
    FD -->|"repair loop ≤3"| EXEC
    EXEC --> PS
    JP -->|"INSERT"| PG
    TG1 & TG2 & TG3 -->|"PUT artifacts"| S3
    JP -->|"batch traces"| LF
    JP -->|"POST /n8n/job-complete"| N8N_EP
    N8N_EP -->|"forward"| N8N_COMMENT
    N8N_COMMENT -->|"PR comment"| GH
    DEV --> DASH
    DASH -->|"GET /jobs"| JOBS_EP
    DETAIL -->|"GET /jobs/{id}"| JOBS_EP
    JOBS_EP -->|"SELECT"| PG
```

## Component Summary

| Component | Technology | Purpose |
|---|---|---|
| FastAPI | Python 3.11, asyncpg, httpx | REST API, webhook ingestion, job creation |
| LangGraph | 0.2.x, asyncio.gather | Parallel agent orchestration |
| Anthropic SDK | claude-haiku / claude-sonnet | LLM calls (two-model routing) |
| PostgreSQL | asyncpg pool | Jobs, traces, generated tests |
| AWS SQS | LocalStack (dev) | Decoupled job queue |
| AWS S3 | LocalStack (dev) | Test artifact storage |
| Langfuse | Raw HTTP ingestion | LLM trace observability |
| n8n | Webhook + GitHub node | PR comment automation |
| Next.js 14 | App Router, Recharts | Real-time dashboard |

## Agent Routing

| Agent | Model | Parallelism |
|---|---|---|
| context_collector | claude-haiku-4-5-20251001 | sequential |
| risk_classifier | claude-haiku-4-5-20251001 | parallel with test parse |
| test_strategist | claude-sonnet-4-6 | sequential |
| test_generator ×3 | claude-sonnet-4-6 | parallel (unit/integration/api) |
| failure_diagnostician | claude-sonnet-4-6 | conditional, max 3 loops |
| pr_summarizer | claude-haiku-4-5-20251001 | sequential |
