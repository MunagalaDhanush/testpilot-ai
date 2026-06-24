from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncGenerator

import boto3
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.config import Settings, get_settings
from backend.db.connection import close_db, get_pool, init_db
from backend.models.schemas import (
    HealthResponse,
    JobCreate,
    JobListResponse,
    JobResponse,
    WebhookGitHubPayload,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info(f"Starting TestPilot AI [{settings.app_env}]")
    await init_db(settings.database_url)
    _ensure_sqs_queue(settings)

    # Start SQS consumer as a background task
    from backend.job_processor import consume_jobs
    consumer_task = asyncio.create_task(consume_jobs(), name="sqs-consumer")

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
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list,
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
) -> str:
    job_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO jobs
                (id, pr_url, repo_name, pr_number, pr_title, diff_content, status)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, 'queued')
            """,
            job_id, pr_url, repo_name, pr_number, pr_title, diff_content,
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


# ---------------------------------------------------------------------------
# Routes
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
    job_id = await _create_job_record(
        pool,
        pr_url=payload.pr_url,
        repo_name=payload.repo_name,
        pr_number=payload.pr_number,
        pr_title=payload.pr_title,
    )
    await _enqueue_job(
        settings, job_id,
        {"pr_url": payload.pr_url, "repo_name": payload.repo_name, "pr_number": payload.pr_number},
    )
    logger.info(f"Webhook accepted: job_id={job_id} pr={payload.pr_url}")
    return {"job_id": job_id, "status": "queued"}


@app.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreate,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    pool = await get_pool()
    job_id = await _create_job_record(
        pool,
        pr_url=body.pr_url,
        repo_name=body.repo_name,
        pr_number=body.pr_number,
        pr_title=body.pr_title,
        diff_content=body.diff_content,
    )
    await _enqueue_job(
        settings, job_id,
        {"pr_url": body.pr_url, "repo_name": body.repo_name,
         "pr_number": body.pr_number, "diff_content": body.diff_content},
    )
    logger.info(f"Job created: job_id={job_id}")
    return {"id": job_id, "status": "queued"}


@app.post("/jobs/test-run")
async def test_run(body: JobCreate) -> dict[str, Any]:
    """
    Synchronous end-to-end pipeline run — bypasses SQS and webhook validation.
    Use this to manually test the full agent pipeline against a real PR.
    """
    pool = await get_pool()
    job_id = await _create_job_record(
        pool,
        pr_url=body.pr_url,
        repo_name=body.repo_name,
        pr_number=body.pr_number,
        pr_title=body.pr_title,
        diff_content=body.diff_content,
    )
    logger.info(f"test-run: starting synchronous pipeline for job_id={job_id}")

    from backend.job_processor import process_job
    final_state = await process_job(job_id)

    job = await _fetch_job_with_traces(pool, job_id)

    return {
        "job_id": job_id,
        "status": job.get("status") if job else "unknown",
        "risk_level": final_state.get("risk_level"),
        "risk_score": final_state.get("risk_score"),
        "risk_reasons": final_state.get("risk_reasons", []),
        "tests_generated": len(final_state.get("generated_tests", [])),
        "execution_results": [
            {
                "file_path": r.file_path,
                "pass_count": r.pass_count,
                "fail_count": r.fail_count,
                "success": r.success,
            }
            for r in final_state.get("execution_results", [])
        ],
        "repair_attempts": final_state.get("repair_attempts", 0),
        "final_summary": final_state.get("final_summary", ""),
        "errors": final_state.get("errors", []),
        "agent_traces": job.get("traces", []) if job else [],
    }


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
    return {"items": items, "total": total, "page": page, "page_size": page_size}


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

    return {"status": "ok" if db_ok else "degraded", "db_connected": db_ok, "version": "0.2.0"}
