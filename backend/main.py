from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any, AsyncGenerator

import boto3
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.config import Settings, get_settings
from backend.db.connection import close_db, get_pool, init_db
from backend.models.schemas import (
    AnalyzeJobRequest,
    AnalyticsResponse,
    HealthResponse,
    JobCreate,
    JobListResponse,
    JobListStats,
    JobResponse,
    SystemStatusResponse,
    WebhookGitHubPayload,
)


async def _check_langfuse(settings: Settings) -> None:
    import httpx
    url = f"{settings.langfuse_host.rstrip('/')}/api/public/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        logger.info(f"Langfuse connection verified → {settings.langfuse_host}")
    except Exception as e:
        logger.error(f"Langfuse connection FAILED: {e}")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info(f"Starting TestPilot AI [{settings.app_env}]")
    await init_db(settings.database_url)
    _ensure_sqs_queue(settings)
    await _check_langfuse(settings)

    from backend.job_processor import consume_jobs, set_consumer_task
    consumer_task = asyncio.create_task(consume_jobs(), name="sqs-consumer")
    set_consumer_task(consumer_task)

    yield

    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await close_db()
    logger.info("TestPilot AI shut down")


def _ensure_sqs_queue(settings: Settings) -> None:
    try:
        sqs = _get_sqs_client(settings)
        sqs.create_queue(QueueName=settings.sqs_queue_name)
        logger.info(f"SQS queue '{settings.sqs_queue_name}' ready")
    except Exception as e:
        logger.warning(f"SQS queue setup skipped: {e}")


def _get_sqs_client(settings: Settings) -> Any:
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_default_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("sqs", **kwargs)


app = FastAPI(
    title="TestPilot AI",
    description="Multi-agent automated test generation platform",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _verify_github_signature(
    payload: bytes, signature_header: str | None, secret: str
) -> bool:
    if not signature_header:
        return False
    try:
        sha_name, signature = signature_header.split("=", 1)
    except ValueError:
        return False
    if sha_name != "sha256":
        return False
    mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature)


async def _create_job_record(
    pool: Any,
    pr_url: str,
    repo_name: str,
    pr_number: int,
    pr_title: str | None = None,
    diff_content: str | None = None,
    source: str = "webhook",
) -> str:
    job_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO jobs
                (id, pr_url, repo_name, pr_number, pr_title, diff_content, status, source)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, 'queued', $7)
            """,
            job_id, pr_url, repo_name, pr_number, pr_title, diff_content, source,
        )
    return job_id


async def _enqueue_job(settings: Settings, job_id: str, payload: dict[str, Any]) -> None:
    try:
        sqs = _get_sqs_client(settings)
        sqs.send_message(
            QueueUrl=settings.sqs_queue_url,
            MessageBody=json.dumps({"job_id": job_id, **payload}),
        )
    except Exception as e:
        logger.warning(f"SQS enqueue failed for job {job_id}: {e}")


async def _fetch_job_with_traces(pool: Any, job_id: str) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1::uuid", job_id)
        if not row:
            return None
        traces = await conn.fetch(
            "SELECT * FROM agent_traces WHERE job_id = $1::uuid ORDER BY created_at", job_id
        )
        tests = await conn.fetch(
            "SELECT * FROM generated_tests WHERE job_id = $1::uuid ORDER BY created_at", job_id
        )
    job = dict(row)
    job["traces"] = [dict(t) for t in traces]
    job["generated_tests"] = [dict(t) for t in tests]
    return job


async def _compute_list_stats(pool: Any) -> JobListStats:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(tests_generated), 0)::int AS total_tests,
                AVG(
                    CASE WHEN pass_count + fail_count > 0
                         THEN pass_count::float / (pass_count + fail_count) * 100
                    END
                ) AS avg_pass_rate,
                AVG(NULLIF(coverage_delta, 0)) AS avg_coverage_delta
            FROM jobs
            WHERE status IN ('completed', 'awaiting_review', 'rejected')
            """
        )
    return JobListStats(
        total_tests_generated=row["total_tests"] or 0,
        avg_pass_rate=round(row["avg_pass_rate"], 1) if row["avg_pass_rate"] else None,
        avg_coverage_delta=round(row["avg_coverage_delta"], 2) if row["avg_coverage_delta"] else None,
    )


# ---------------------------------------------------------------------------
# Routes — jobs
# ---------------------------------------------------------------------------

@app.post("/webhook/github", status_code=status.HTTP_202_ACCEPTED)
async def webhook_github(
    request: Request,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    raw_body = await request.body()
    if not _verify_github_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    try:
        payload = WebhookGitHubPayload.model_validate(json.loads(raw_body))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid payload: {e}")
    if payload.action not in ("opened", "synchronize", "reopened"):
        return {"status": "ignored", "action": payload.action}
    pool = await get_pool()
    job_id = await _create_job_record(pool, payload.pr_url, payload.repo_name,
                                       payload.pr_number, payload.pr_title)
    await _enqueue_job(settings, job_id,
                       {"pr_url": payload.pr_url, "repo_name": payload.repo_name,
                        "pr_number": payload.pr_number})
    logger.info(f"Webhook accepted: job_id={job_id}")
    return {"job_id": job_id, "status": "queued"}


@app.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_job(body: JobCreate, settings: Settings = Depends(get_settings)) -> dict[str, str]:
    pool = await get_pool()
    job_id = await _create_job_record(pool, body.pr_url, body.repo_name,
                                       body.pr_number, body.pr_title, body.diff_content)
    await _enqueue_job(settings, job_id,
                       {"pr_url": body.pr_url, "repo_name": body.repo_name,
                        "pr_number": body.pr_number, "diff_content": body.diff_content})
    return {"id": job_id, "status": "queued"}


@app.post("/jobs/analyze", status_code=status.HTTP_201_CREATED)
async def analyze_job(
    body: AnalyzeJobRequest,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if not body.pr_url and not body.diff_content:
        raise HTTPException(
            status_code=422,
            detail="Provide either pr_url or diff_content",
        )
    pr_number = body.pr_number or 0
    pr_url = body.pr_url or f"https://github.com/{body.repo_name}/pull/{pr_number}"
    pool = await get_pool()
    job_id = await _create_job_record(
        pool, pr_url, body.repo_name, pr_number,
        diff_content=body.diff_content, source="manual",
    )
    await _enqueue_job(settings, job_id, {
        "pr_url": pr_url,
        "repo_name": body.repo_name,
        "pr_number": pr_number,
        "diff_content": body.diff_content,
    })
    logger.info(f"Manual analysis job created: {job_id}")
    return {"job_id": job_id, "status": "queued"}


@app.post("/jobs/test-run")
async def test_run(body: JobCreate) -> dict[str, Any]:
    pool = await get_pool()
    job_id = await _create_job_record(pool, body.pr_url, body.repo_name,
                                       body.pr_number, body.pr_title, body.diff_content)
    from backend.job_processor import process_job
    final_state = await process_job(job_id)
    job = await _fetch_job_with_traces(pool, job_id)
    return {
        "job_id": job_id,
        "status": job.get("status") if job else "unknown",
        "risk_level": final_state.get("risk_level"),
        "tests_generated": len(final_state.get("generated_tests", [])),
        "repair_attempts": final_state.get("repair_attempts", 0),
        "final_summary": final_state.get("final_summary", ""),
        "errors": final_state.get("errors", []),
    }


@app.post("/jobs/{job_id}/approve")
async def approve_job(job_id: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1::uuid", job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        if row["status"] != "awaiting_review":
            raise HTTPException(
                status_code=409,
                detail=f"Job is '{row['status']}', not 'awaiting_review'",
            )
        await conn.execute(
            """
            UPDATE jobs
               SET human_approved = TRUE,
                   human_reviewed_at = $2,
                   status = 'completed',
                   updated_at = NOW()
             WHERE id = $1::uuid
            """,
            job_id,
            datetime.now(timezone.utc),
        )

    from backend.job_processor import resume_job
    await resume_job(job_id)
    logger.info(f"Job {job_id} approved — n8n notified")
    return {"job_id": job_id, "status": "completed", "human_approved": True}


@app.post("/jobs/{job_id}/reject")
async def reject_job(job_id: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1::uuid", job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        await conn.execute(
            """
            UPDATE jobs
               SET human_approved = FALSE,
                   human_reviewed_at = $2,
                   status = 'rejected',
                   updated_at = NOW()
             WHERE id = $1::uuid
            """,
            job_id,
            datetime.now(timezone.utc),
        )
    logger.info(f"Job {job_id} rejected")
    return {"job_id": job_id, "status": "rejected", "human_approved": False}


@app.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> dict[str, Any]:
    pool = await get_pool()
    job = await _fetch_job_with_traces(pool, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@app.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    pool = await get_pool()
    offset = (page - 1) * page_size
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM jobs")
        rows = await conn.fetch(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            page_size, offset,
        )
    items = [{**dict(row), "traces": [], "generated_tests": []} for row in rows]
    stats = await _compute_list_stats(pool)
    return {"items": items, "total": total, "page": page, "page_size": page_size, "stats": stats}


# ---------------------------------------------------------------------------
# Routes — system control
# ---------------------------------------------------------------------------

@app.post("/system/pause")
async def pause_system() -> dict[str, bool]:
    from backend.job_processor import pause_consumer
    pause_consumer()
    return {"paused": True}


@app.post("/system/resume")
async def resume_system() -> dict[str, bool]:
    from backend.job_processor import resume_consumer
    resume_consumer()
    return {"paused": False}


@app.post("/system/stop")
async def stop_system() -> dict[str, Any]:
    from backend.job_processor import stop_consumer
    stop_consumer()
    return {"stopped": True, "paused": True}


@app.post("/system/restart")
async def restart_system_endpoint() -> dict[str, Any]:
    from backend.job_processor import restart_consumer
    await restart_consumer()
    return {"paused": False, "stopped": False, "active": True}


@app.post("/system/fetch-github")
async def fetch_github(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Trigger seeder to pull latest merged PRs from configured GitHub repos."""
    import os
    import httpx

    token = os.getenv("GITHUB_TOKEN", "")
    repos = os.getenv("GITHUB_REPOS", "fastapi/fastapi,pydantic/pydantic").split(",")
    repos = [r.strip() for r in repos if r.strip()]
    created: list[str] = []
    pool = await get_pool()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for repo in repos:
            owner, name = (repo.split("/") + [""])[:2]
            if not owner or not name:
                continue
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{name}/pulls",
                    headers=headers,
                    params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 5},
                )
                resp.raise_for_status()
                for pr in resp.json():
                    if not pr.get("merged_at"):
                        continue
                    job_id = await _create_job_record(
                        pool,
                        pr["html_url"],
                        repo,
                        pr["number"],
                        pr.get("title", ""),
                        pr.get("body") or "",
                        source="seeded",
                    )
                    await _enqueue_job(settings, job_id, {
                        "pr_url": pr["html_url"],
                        "repo_name": repo,
                        "pr_number": pr["number"],
                    })
                    created.append(job_id)
            except Exception as e:
                logger.warning(f"GitHub fetch failed for {repo}: {e}")

    logger.info(f"fetch-github: created {len(created)} jobs")
    return {"jobs_created": len(created), "job_ids": created}


@app.get("/system/status", response_model=SystemStatusResponse)
async def system_status() -> dict[str, Any]:
    from backend.job_processor import is_consumer_paused, is_consumer_stopped
    pool = await get_pool()
    async with pool.acquire() as conn:
        active = await conn.fetchval(
            "SELECT COUNT(*) FROM jobs WHERE status = 'processing'"
        )
        queued = await conn.fetchval(
            "SELECT COUNT(*) FROM jobs WHERE status = 'queued'"
        )
        awaiting = await conn.fetchval(
            "SELECT COUNT(*) FROM jobs WHERE status = 'awaiting_review'"
        )
    paused = is_consumer_paused()
    stopped = is_consumer_stopped()
    return {
        "paused": paused,
        "stopped": stopped,
        "active": not paused and not stopped,
        "active_jobs": active,
        "queued_jobs": queued,
        "awaiting_review": awaiting,
    }


# ---------------------------------------------------------------------------
# Routes — analytics
# ---------------------------------------------------------------------------

@app.get("/analytics", response_model=AnalyticsResponse)
async def analytics() -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        pass_rate_rows = await conn.fetch(
            """
            SELECT
                TO_CHAR(DATE_TRUNC('day', created_at), 'YYYY-MM-DD') AS date,
                ROUND(
                    AVG(CASE WHEN pass_count + fail_count > 0
                             THEN pass_count::float / (pass_count + fail_count) * 100
                        END)::numeric, 1
                )::float AS pass_rate,
                COUNT(*)::int AS total_jobs
            FROM jobs
            WHERE status IN ('completed', 'awaiting_review', 'rejected')
              AND (pass_count + fail_count) > 0
            GROUP BY DATE_TRUNC('day', created_at)
            ORDER BY DATE_TRUNC('day', created_at)
            LIMIT 30
            """
        )
        risk_rows = await conn.fetch(
            """
            SELECT risk_level, COUNT(*)::int AS count
            FROM jobs
            WHERE risk_level IS NOT NULL
            GROUP BY risk_level
            ORDER BY count DESC
            """
        )
        agent_rows = await conn.fetch(
            """
            SELECT
                agent_name,
                MAX(model_used) AS model_used,
                AVG(latency_ms)::int AS avg_latency_ms,
                COUNT(*)::int AS run_count
            FROM agent_traces
            WHERE latency_ms IS NOT NULL
            GROUP BY agent_name
            ORDER BY avg_latency_ms DESC
            """
        )
        token_rows = await conn.fetch(
            """
            SELECT
                j.id::text AS job_id,
                TO_CHAR(j.created_at, 'YYYY-MM-DD') AS date,
                COALESCE(SUM(
                    CASE WHEN at.model_used LIKE '%haiku%'
                         THEN COALESCE(at.input_tokens,0) + COALESCE(at.output_tokens,0)
                    END
                ), 0)::int AS haiku_tokens,
                COALESCE(SUM(
                    CASE WHEN at.model_used LIKE '%sonnet%'
                         THEN COALESCE(at.input_tokens,0) + COALESCE(at.output_tokens,0)
                    END
                ), 0)::int AS sonnet_tokens
            FROM jobs j
            LEFT JOIN agent_traces at ON at.job_id = j.id
            WHERE j.status IN ('completed', 'awaiting_review', 'rejected')
            GROUP BY j.id, j.created_at
            ORDER BY j.created_at DESC
            LIMIT 20
            """
        )

    return {
        "pass_rate_over_time": [dict(r) for r in pass_rate_rows],
        "risk_distribution": [dict(r) for r in risk_rows],
        "agent_performance": [dict(r) for r in agent_rows],
        "model_tokens_per_job": [dict(r) for r in token_rows],
    }


# ---------------------------------------------------------------------------
# Routes — n8n + health
# ---------------------------------------------------------------------------

@app.post("/n8n/job-complete")
async def n8n_job_complete(
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if not settings.n8n_webhook_url:
        return {"status": "skipped"}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.n8n_webhook_url, json=body)
            resp.raise_for_status()
        return {"status": "ok"}
    except Exception as e:
        logger.warning(f"n8n notification failed: {e}")
        return {"status": "error", "detail": str(e)}


@app.get("/health", response_model=HealthResponse)
async def health() -> dict[str, Any]:
    db_ok = False
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_ok = True
    except Exception as e:
        logger.warning(f"DB health check failed: {e}")
    return {"status": "ok" if db_ok else "degraded", "db_connected": db_ok, "version": "0.3.0"}
