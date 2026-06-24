from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from backend.config import get_settings


class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.github_token
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        attempt: int = 1,
    ) -> Any:
        url = f"{self.BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method, url, headers=self._headers, json=json, params=params
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt <= 3:
                    wait = 2 ** attempt
                    logger.warning(f"GitHub rate limit hit, retrying in {wait}s (attempt {attempt})")
                    await asyncio.sleep(wait)
                    return await self._request(method, path, json=json, params=params, attempt=attempt + 1)
                raise

    async def get_pull_request(self, repo_name: str, pr_number: int) -> dict[str, Any]:
        return await self._request("GET", f"/repos/{repo_name}/pulls/{pr_number}")

    async def get_pull_request_diff(self, repo_name: str, pr_number: int) -> str:
        url = f"{self.BASE_URL}/repos/{repo_name}/pulls/{pr_number}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={**self._headers, "Accept": "application/vnd.github.diff"},
            )
            response.raise_for_status()
            return response.text

    async def get_pull_request_files(self, repo_name: str, pr_number: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/repos/{repo_name}/pulls/{pr_number}/files")

    async def get_file_content(self, repo_name: str, file_path: str, ref: str) -> str:
        data = await self._request(
            "GET",
            f"/repos/{repo_name}/contents/{file_path}",
            params={"ref": ref},
        )
        import base64
        return base64.b64decode(data["content"]).decode("utf-8")

    async def post_pr_comment(self, repo_name: str, pr_number: int, body: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/repos/{repo_name}/issues/{pr_number}/comments",
            json={"body": body},
        )

    async def get_existing_tests(self, repo_name: str, ref: str) -> list[str]:
        """Return list of test file paths in the repository at the given ref."""
        try:
            tree = await self._request(
                "GET",
                f"/repos/{repo_name}/git/trees/{ref}",
                params={"recursive": "1"},
            )
            test_files = [
                item["path"]
                for item in tree.get("tree", [])
                if item["type"] == "blob" and (
                    "test" in item["path"].lower() or "spec" in item["path"].lower()
                )
            ]
            return test_files
        except Exception as e:
            logger.warning(f"Could not fetch existing tests for {repo_name}@{ref}: {e}")
            return []
