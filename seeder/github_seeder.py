"""Manual job injector for local testing — bypasses webhook signature validation."""

import asyncio
import json
import sys
from typing import Any

import httpx
from loguru import logger

BASE_URL = "http://localhost:8000"

SAMPLE_PAYLOAD: dict[str, Any] = {
    "pr_url": "https://github.com/octocat/Hello-World/pull/1",
    "repo_name": "octocat/Hello-World",
    "pr_number": 1,
    "pr_title": "Fix memory leak in connection pool",
    "diff_content": """\
diff --git a/src/pool.py b/src/pool.py
index a1b2c3d..e4f5a6b 100644
--- a/src/pool.py
+++ b/src/pool.py
@@ -12,6 +12,8 @@ class ConnectionPool:
     def release(self, conn):
         self._pool.append(conn)
+        if len(self._pool) > self._max_size:
+            conn.close()

     def close_all(self):
         for conn in self._pool:
""",
}


async def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        response = await client.post("/jobs", json=payload)
        response.raise_for_status()
        return response.json()


async def get_job(job_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        response = await client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        return response.json()


async def poll_until_done(job_id: str, max_polls: int = 60) -> dict[str, Any]:
    for i in range(max_polls):
        job = await get_job(job_id)
        status = job.get("status")
        logger.info(f"Poll {i + 1}/{max_polls} — job {job_id} status: {status}")
        if status in ("completed", "failed"):
            return job
        await asyncio.sleep(5)
    raise TimeoutError(f"Job {job_id} did not complete after {max_polls * 5}s")


async def main() -> None:
    logger.info("Checking backend health...")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        health = await client.get("/health")
        health.raise_for_status()
        logger.info(f"Health: {health.json()}")

    logger.info("Creating test job...")
    job = await create_job(SAMPLE_PAYLOAD)
    job_id = job["id"]
    logger.info(f"Created job {job_id}")

    logger.info("Polling for completion...")
    final = await poll_until_done(job_id)
    logger.info("Final job state:")
    print(json.dumps(final, indent=2, default=str))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Seeder failed: {e}")
        sys.exit(1)
