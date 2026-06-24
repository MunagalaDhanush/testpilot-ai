from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import docker
from docker.errors import ContainerError, DockerException, ImageNotFound
from loguru import logger

from backend.models.schemas import GeneratedTest, TestExecutionResult


SANDBOX_IMAGE = "testpilot-sandbox"
SANDBOX_TIMEOUT_SECONDS = 120


class DockerRunner:
    def __init__(self) -> None:
        try:
            self._client = docker.from_env()
        except DockerException as e:
            logger.error(f"Docker not available: {e}")
            raise

    def _ensure_sandbox_image(self) -> None:
        try:
            self._client.images.get(SANDBOX_IMAGE)
        except ImageNotFound:
            sandbox_dockerfile = Path(__file__).parent.parent.parent / "sandbox" / "Dockerfile"
            logger.info(f"Building sandbox image from {sandbox_dockerfile}...")
            self._client.images.build(
                path=str(sandbox_dockerfile.parent),
                tag=SANDBOX_IMAGE,
                rm=True,
            )
            logger.info(f"Sandbox image '{SANDBOX_IMAGE}' built.")

    def run_tests(self, tests: list[GeneratedTest], job_id: str) -> list[TestExecutionResult]:
        self._ensure_sandbox_image()
        results: list[TestExecutionResult] = []

        with tempfile.TemporaryDirectory(prefix=f"testpilot-{job_id}-") as tmpdir:
            tests_dir = Path(tmpdir) / "tests"
            tests_dir.mkdir()

            for test in tests:
                test_file = tests_dir / Path(test.file_path).name
                test_file.write_text(test.file_content, encoding="utf-8")

            result = self._run_container(tmpdir)
            results = self._parse_results(result, tests)

        return results

    def _run_container(self, host_dir: str) -> dict[str, Any]:
        try:
            container = self._client.containers.run(
                SANDBOX_IMAGE,
                volumes={host_dir: {"bind": "/sandbox", "mode": "rw"}},
                remove=False,
                detach=True,
                network_disabled=True,
                mem_limit="256m",
                cpu_period=100000,
                cpu_quota=50000,
            )
            exit_code = container.wait(timeout=SANDBOX_TIMEOUT_SECONDS)["StatusCode"]
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            container.remove()

            results_path = Path(host_dir) / "results.json"
            if results_path.exists():
                with open(results_path) as f:
                    parsed = json.load(f)
                return {"exit_code": exit_code, "logs": logs, "parsed": parsed}
            return {"exit_code": exit_code, "logs": logs, "parsed": {}}

        except ContainerError as e:
            logger.error(f"Container error: {e}")
            return {"exit_code": 1, "logs": str(e), "parsed": {}}
        except Exception as e:
            logger.error(f"Docker run failed: {e}")
            return {"exit_code": 1, "logs": str(e), "parsed": {}}

    def _parse_results(
        self, raw: dict[str, Any], tests: list[GeneratedTest]
    ) -> list[TestExecutionResult]:
        parsed = raw.get("parsed", {})
        results: list[TestExecutionResult] = []

        if not parsed:
            for test in tests:
                results.append(
                    TestExecutionResult(
                        file_path=test.file_path,
                        success=False,
                        error_output=raw.get("logs", ""),
                    )
                )
            return results

        summary = parsed.get("summary", {})
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        success = failed == 0 and raw.get("exit_code", 1) == 0

        for test in tests:
            results.append(
                TestExecutionResult(
                    file_path=test.file_path,
                    pass_count=passed,
                    fail_count=failed,
                    success=success,
                    error_output="" if success else raw.get("logs", ""),
                )
            )

        return results
