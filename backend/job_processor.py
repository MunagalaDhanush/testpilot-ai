from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import boto3
import httpx
from loguru import logger

from backend.config import get_settings
from backend.db.connection import get_pool
from backend.graph.pipeline import get_pipeline
from backend.graph.state import PipelineState
from backend.models.schemas import GeneratedTest, TestExecutionResult

SQS_POLL_INTERVAL = 5

# ---------------------------------------------------------------------------
# Pause / resume gate — cleared = paused, set = active
# ---------------------------------------------------------------------------

_consumer_active: asyncio.Event = asyncio.Event()
_consumer_active.set()  # starts active

_consumer_stopped: bool = False


def pause_consumer() -> None:
    _consumer_active.clear()
    logger.info("SQS consumer paused")


def resume_consumer() -> None:
    _consumer_active.set()
    logger.info("SQS consumer resumed")


def is_consumer_paused() -> bool:
    return not _consumer_active.is_set()


def stop_consumer() -> None:
    global _consumer_stopped
    _consumer_stopped = True
    _consumer_active.clear()
    logger.info("SQS consumer stopped")


def is_consumer_stopped() -> bool:
    return _consumer_stopped


_consumer_task: asyncio.Task | None = None


def set_consumer_task(task: asyncio.Task) -> None:
    global _consumer_task
    _consumer_task = task


async def restart_consumer() -> None:
    global _consumer_stopped, _consumer_task
    _consumer_stopped = False
    _consumer_active.set()
    if _consumer_task is None or _consumer_task.done():
        _consumer_task = asyncio.create_task(consume_jobs(), name="sqs-consumer")
        logger.info("SQS consumer restarted — new task created")
    else:
        logger.info("SQS consumer restart: flags reset, existing task still running")


# ---------------------------------------------------------------------------
# Core job processor
# ---------------------------------------------------------------------------

async def process_job(job_id: str) -> PipelineState:
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1::uuid", job_id)
    if not row:
        raise ValueError(f"Job {job_id} not found in database")

    job = dict(row)
    logger.bind(job_id=job_id).info(f"Processing job for PR {job['pr_url']}")

    await _update_job_status(job_id, "processing")

    initial_state: PipelineState = {
        "job_id": job_id,
        "pr_url": job["pr_url"],
        "repo_name": job["repo_name"],
        "pr_number": job["pr_number"],
        "diff_content": job.get("diff_content") or "",
        "changed_files": [],
        "changed_functions": [],
        "existing_tests": [],
        "existing_coverage": {},
        "risk_level": "",
        "risk_score": 0.0,
        "risk_reasons": [],
        "test_strategy": {},
        "generated_tests": [],
        "execution_results": [],
        "repair_diagnosis": [],
        "repair_attempts": 0,
        "final_summary": "",
        "errors": [],
    }

    pipeline = get_pipeline()
    try:
        final_state: PipelineState = await pipeline.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"Pipeline failed for job {job_id}: {e}")
        await _update_job_status(job_id, "failed")
        raise

    await _save_generated_tests(job_id, final_state)
    await _finalize_job_record(job_id, final_state)

    # Ship traces to Langfuse (best-effort)
    pool = await get_pool()
    async with pool.acquire() as conn:
        trace_rows = await conn.fetch(
            "SELECT * FROM agent_traces WHERE job_id = $1::uuid ORDER BY created_at",
            job_id,
        )
    await send_to_langfuse(job_id, [dict(r) for r in trace_rows])

    logger.bind(job_id=job_id).info("Job awaiting human review")
    return final_state


async def resume_job(job_id: str) -> None:
    """Called from the /approve endpoint — notifies n8n to post the PR comment."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1::uuid", job_id)
    if not row:
        raise ValueError(f"Job {job_id} not found")
    job = dict(row)
    await _notify_n8n(job_id, job["pr_url"], job["repo_name"], job["pr_number"])


# ---------------------------------------------------------------------------
# SQS consumer loop
# ---------------------------------------------------------------------------

async def consume_jobs() -> None:
    settings = get_settings()
    sqs = _make_sqs_client(settings)
    queue_url = settings.sqs_queue_url

    logger.info(f"SQS consumer started — polling {queue_url} every {SQS_POLL_INTERVAL}s")

    async def _process_and_ack(job_id: str, receipt: str) -> None:
        try:
            await process_job(job_id)
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
            logger.info(f"SQS: deleted message for job_id={job_id}")
        except Exception as e:
            logger.error(f"SQS: job processing failed, leaving message for retry: {e}")

    while True:
        try:
            if _consumer_stopped:
                logger.info("SQS consumer: stopped flag set, exiting")
                return

            # Block here while paused — wakes immediately when resumed
            await _consumer_active.wait()

            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=3,
                WaitTimeSeconds=5,
                VisibilityTimeout=300,
            )
            messages = response.get("Messages", [])

            if messages:
                tasks = []
                for msg in messages:
                    body = json.loads(msg["Body"])
                    job_id: str = body["job_id"]
                    logger.info(f"SQS: received job_id={job_id}")
                    tasks.append(_process_and_ack(job_id, msg["ReceiptHandle"]))
                await asyncio.gather(*tasks, return_exceptions=True)

        except asyncio.CancelledError:
            logger.info("SQS consumer shutting down")
            return
        except Exception as e:
            logger.warning(f"SQS receive_message error: {e}")

        await asyncio.sleep(SQS_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sqs_client(settings: Any) -> Any:
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_default_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("sqs", **kwargs)


async def _finalize_job_record(job_id: str, state: PipelineState) -> None:
    """Persists final_summary, risk info, and aggregate test stats. Sets status=awaiting_review."""
    tests: list[GeneratedTest] = state.get("generated_tests", [])
    results: list[TestExecutionResult] = state.get("execution_results", [])

    tests_generated = len(tests)
    pass_count = sum(r.pass_count for r in results)
    fail_count = sum(r.fail_count for r in results)
    coverage_delta = (
        sum(r.coverage_delta for r in results) / len(results) if results else 0.0
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE jobs SET
                status          = 'awaiting_review',
                risk_level      = $2,
                final_summary   = $3,
                tests_generated = $4,
                pass_count      = $5,
                fail_count      = $6,
                coverage_delta  = $7,
                updated_at      = NOW()
            WHERE id = $1::uuid
            """,
            job_id,
            state.get("risk_level") or None,
            state.get("final_summary") or None,
            tests_generated,
            pass_count,
            fail_count,
            coverage_delta,
        )


async def send_to_langfuse(job_id: str, agent_traces: list[dict[str, Any]]) -> None:
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.debug("Langfuse credentials not set — skipping trace upload")
        return

    batch = [
        {
            "id": str(trace["id"]),
            "type": "trace-create",
            "timestamp": (
                trace["created_at"].isoformat()
                if hasattr(trace["created_at"], "isoformat")
                else str(trace["created_at"])
            ),
            "body": {
                "id": str(trace["id"]),
                "name": trace["agent_name"],
                "metadata": {
                    "model": trace["model_used"],
                    "input_tokens": trace["input_tokens"],
                    "output_tokens": trace["output_tokens"],
                    "latency_ms": trace["latency_ms"],
                    "job_id": job_id,
                },
            },
        }
        for trace in agent_traces
    ]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{host.rstrip('/')}/api/public/ingestion",
                auth=(public_key, secret_key),
                json={"batch": batch},
            )
            resp.raise_for_status()
        logger.info(f"Langfuse: uploaded {len(batch)} traces for job {job_id}")
    except Exception as e:
        logger.warning(f"Langfuse trace upload failed for job {job_id}: {e}")


async def _notify_n8n(
    job_id: str,
    pr_url: str,
    repo_name: str,
    pr_number: int,
) -> None:
    settings = get_settings()
    if not settings.n8n_webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.n8n_webhook_url,
                json={"job_id": job_id, "pr_url": pr_url,
                      "repo_name": repo_name, "pr_number": pr_number},
            )
            resp.raise_for_status()
        logger.info(f"n8n notified for job {job_id}")
    except Exception as e:
        logger.warning(f"n8n notification failed for job {job_id}: {e}")


async def _update_job_status(job_id: str, status: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE jobs SET status = $2, updated_at = NOW() WHERE id = $1::uuid",
            job_id, status,
        )


async def _save_generated_tests(job_id: str, state: PipelineState) -> None:
    generated: list[GeneratedTest] = state.get("generated_tests", [])
    results: list[TestExecutionResult] = state.get("execution_results", [])
    repair_attempts: int = state.get("repair_attempts", 0)
    result_map = {r.file_path: r for r in results}

    pool = await get_pool()
    async with pool.acquire() as conn:
        for test in generated:
            result = result_map.get(test.file_path)
            await conn.execute(
                """
                INSERT INTO generated_tests
                    (job_id, test_type, file_content, file_path,
                     pass_count, fail_count, coverage_delta, repair_attempts)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT DO NOTHING
                """,
                job_id,
                test.test_type,
                test.file_content,
                test.file_path,
                result.pass_count if result else 0,
                result.fail_count if result else 0,
                result.coverage_delta if result else 0.0,
                repair_attempts,
            )
