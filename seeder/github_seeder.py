"""
Fetch merged PRs from popular Python repos and seed them into TestPilot AI.

Usage:
    python seeder/github_seeder.py

Requires GITHUB_TOKEN in .env or environment.
Requires the API to be running at http://localhost:8000.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx
from loguru import logger

BASE_URL = os.getenv("TESTPILOT_API_URL", "http://localhost:8000")

REPOS = [
    "fastapi/fastapi",
    "pydantic/pydantic",
]

PRS_PER_REPO = 25  # 25 × 2 repos = 50 total


async def _github_get(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """GET from GitHub API with exponential-backoff retry (max 3)."""
    token = os.getenv("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com{path}"
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=20.0)
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                wait = 2 ** attempt * 10
                logger.warning(f"GitHub rate limit hit — waiting {wait}s")
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response.status_code in (404, 422):
                raise
            await asyncio.sleep(2 ** attempt)
        except httpx.RequestError as e:
            last_err = e
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"GitHub API failed after 3 attempts: {last_err}")


async def fetch_merged_prs(
    client: httpx.AsyncClient,
    repo: str,
    count: int,
) -> list[dict[str, Any]]:
    """Return up to `count` merged PRs that touched at least one Python file."""
    owner, name = repo.split("/")
    results: list[dict[str, Any]] = []
    page = 1

    while len(results) < count:
        pulls = await _github_get(
            client,
            f"/repos/{owner}/{name}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": 30,
                "page": page,
            },
        )
        if not pulls:
            break

        for pr in pulls:
            if len(results) >= count:
                break
            # Only merged PRs
            if not pr.get("merged_at"):
                continue
            # Check files changed for Python content
            try:
                files = await _github_get(
                    client,
                    f"/repos/{owner}/{name}/pulls/{pr['number']}/files",
                    params={"per_page": 30},
                )
                py_files = [f for f in files if f["filename"].endswith(".py")]
                if not py_files:
                    continue
            except Exception as e:
                logger.debug(f"Skipping PR #{pr['number']}: {e}")
                continue

            results.append(
                {
                    "pr_url": pr["html_url"],
                    "repo_name": repo,
                    "pr_number": pr["number"],
                    "pr_title": pr.get("title", ""),
                    # Use the PR body as a stand-in diff (real diff requires another API call)
                    "diff_content": pr.get("body") or "",
                    "source": "seeded",
                }
            )
            logger.info(f"  Found: {repo} #{pr['number']} — {pr.get('title', '')[:60]}")

        page += 1
        # Avoid hammering the API
        await asyncio.sleep(0.5)

    return results[:count]


async def create_job(api: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(1, 4):
        try:
            resp = await api.post("/jobs", json=payload, timeout=15.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"POST /jobs attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to create job for {payload['repo_name']} #{payload['pr_number']}")


async def main() -> None:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        logger.warning(
            "GITHUB_TOKEN not set — unauthenticated requests are rate-limited to 60/hour"
        )

    # Verify API is reachable
    async with httpx.AsyncClient(base_url=BASE_URL) as api:
        try:
            health = await api.get("/health", timeout=5.0)
            health.raise_for_status()
            logger.info(f"API health: {health.json()}")
        except Exception as e:
            logger.error(f"Cannot reach API at {BASE_URL}: {e}")
            sys.exit(1)

    created: list[dict[str, Any]] = []

    async with httpx.AsyncClient() as gh, httpx.AsyncClient(base_url=BASE_URL) as api:
        for repo in REPOS:
            logger.info(f"Fetching {PRS_PER_REPO} merged Python PRs from {repo}…")
            try:
                prs = await fetch_merged_prs(gh, repo, PRS_PER_REPO)
            except Exception as e:
                logger.error(f"Failed to fetch PRs from {repo}: {e}")
                continue

            for pr in prs:
                try:
                    job = await create_job(api, pr)
                    created.append(job)
                    logger.info(
                        f"  ✓ Created job {job.get('id', '?')} for "
                        f"{repo} #{pr['pr_number']}"
                    )
                except Exception as e:
                    logger.error(f"  ✗ {repo} #{pr['pr_number']}: {e}")

            await asyncio.sleep(1)

    logger.info(f"\nSeeding complete — {len(created)} jobs created")
    if created:
        print(json.dumps({"seeded": len(created), "sample": created[:3]}, indent=2, default=str))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Seeder interrupted")
    except Exception as e:
        logger.error(f"Seeder failed: {e}")
        sys.exit(1)
