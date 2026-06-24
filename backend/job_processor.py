from __future__ import annotations

import asyncio
import json
from typing import Any

import boto3
from loguru import logger

from backend.config import get_settings
from backend.db.connection import get_pool
from backend.graph.pipeline import get_pipeline
from backend.graph.state import PipelineState
from backend.models.schemas import GeneratedTest, TestExecutionResult

SQS_POLL_INTERVAL = 5  # seconds between receive calls


# ---------------------------------------------------------------------------
# Core job processor
# ---------------------------------------------------------------------------

async def process_job(job_id: str) -> PipelineState:
    """
    Fetch job from DB, run the full LangGraph pipeline, persist results.
    Returns the final pipeline state.
    """
    pool = await get_pool()

    # 1. Fetch job row
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1::uuid", job_id)
    if not row:
        raise ValueError(f"Job {job_id} not found in database")

    job = dict(row)
    logger.bind(job_id=job_id).info(f"Processing job for PR {job['pr_url']}")

    # 2. Mark as processing
    await _update_job_status(job_id, "processing")

    # 3. Build initial pipeline state
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

    # 4. Run the pipeline
    pipeline = get_pipeline()
    try:
        final_state: PipelineState = await pipeline.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"Pipeline failed for job {job_id}: {e}")
        await _update_job_status(job_id, "failed", risk_level=None)
        raise

    # 5. Persist generated tests + execution results
    await _save_generated_tests(job_id, final_state)

    # 6. Update job to completed
    await _update_job_status(
        job_id,
        "completed",
        risk_level=final_state.get("risk_level"),
    )

    logger.bind(job_id=job_id).info("Job completed successfully")
    return final_state


# ---------------------------------------------------------------------------
# SQS consumer loop
# ---------------------------------------------------------------------------

async def consume_jobs() -> None:
    """
    Poll SQS every SQS_POLL_INTERVAL seconds.
    On success the message is deleted; on failure it remains for SQS retry.
    """
    settings = get_settings()
    sqs = _make_sqs_client(settings)
    queue_url = settings.sqs_queue_url

    logger.info(f"SQS consumer started — polling {queue_url} every {SQS_POLL_INTERVAL}s")

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=5,  # long-poll
                VisibilityTimeout=300,  # 5 min — enough for the pipeline
            )
            messages = response.get("Messages", [])

            for msg in messages:
                receipt = msg["ReceiptHandle"]
                try:
                    body = json.loads(msg["Body"])
                    job_id: str = body["job_id"]
                    logger.info(f"SQS: received job_id={job_id}")
                    await process_job(job_id)
                    sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
                    logger.info(f"SQS: deleted message for job_id={job_id}")
                except Exception as e:
                    logger.error(f"SQS: job processing failed, leaving message for retry: {e}")

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


async def _update_job_status(
    job_id: str,
    status: str,
    risk_level: str | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE jobs
               SET status = $2,
                   risk_level = COALESCE($3, risk_level),
                   updated_at = NOW()
             WHERE id = $1::uuid
            """,
            job_id,
            status,
            risk_level,
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
