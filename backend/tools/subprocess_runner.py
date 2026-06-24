from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from backend.models.schemas import GeneratedTest, TestExecutionResult

PYTEST_TIMEOUT = 60  # seconds per test run


class SubprocessRunner:
    """
    Runs pytest via subprocess inside the API container.
    Phase 2 replaces Docker-in-Docker with this approach.
    Phase 3 will reintroduce isolated sandbox containers.
    """

    async def run_tests(
        self, tests: list[GeneratedTest], job_id: str
    ) -> list[TestExecutionResult]:
        with tempfile.TemporaryDirectory(prefix=f"testpilot-{job_id}-") as tmpdir:
            tmp = Path(tmpdir)
            tests_dir = tmp / "tests"
            tests_dir.mkdir()
            report_path = tmp / "report.json"

            for test in tests:
                dest = tests_dir / Path(test.file_path).name
                dest.write_text(test.file_content, encoding="utf-8")
                logger.debug(f"Wrote test file: {dest}")

            exit_code, stdout, stderr = await self._run_pytest(tests_dir, report_path)
            raw_output = stdout + stderr

            report: dict[str, Any] = {}
            if report_path.exists():
                try:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    logger.warning("subprocess_runner: could not parse pytest JSON report")

            return self._build_results(tests, exit_code, raw_output, report)

    async def _run_pytest(
        self, tests_dir: Path, report_path: Path
    ) -> tuple[int, str, str]:
        cmd = [
            sys.executable, "-m", "pytest",
            str(tests_dir),
            "--json-report",
            f"--json-report-file={report_path}",
            "-v",
            "--tb=short",
            "--no-header",
        ]
        logger.info(f"Running: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=PYTEST_TIMEOUT
            )
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0
            logger.info(f"pytest exited {exit_code}")
            return exit_code, stdout, stderr

        except asyncio.TimeoutError:
            logger.error(f"pytest timed out after {PYTEST_TIMEOUT}s")
            return 1, "", f"TimeoutError: pytest exceeded {PYTEST_TIMEOUT}s"
        except Exception as e:
            logger.error(f"subprocess_runner: unexpected error — {e}")
            return 1, "", str(e)

    def _build_results(
        self,
        tests: list[GeneratedTest],
        exit_code: int,
        raw_output: str,
        report: dict[str, Any],
    ) -> list[TestExecutionResult]:
        summary = report.get("summary", {})
        total_passed = summary.get("passed", 0)
        total_failed = summary.get("failed", 0) + summary.get("error", 0)
        overall_success = exit_code == 0 and total_failed == 0

        # Map individual test results by nodeid for per-file breakdown
        per_file: dict[str, dict[str, int]] = {}
        for t in report.get("tests", []):
            file_key = t.get("nodeid", "").split("::")[0]
            if file_key not in per_file:
                per_file[file_key] = {"passed": 0, "failed": 0}
            if t.get("outcome") == "passed":
                per_file[file_key]["passed"] += 1
            else:
                per_file[file_key]["failed"] += 1

        results: list[TestExecutionResult] = []
        for test in tests:
            filename = Path(test.file_path).name
            # match by filename suffix since tmpdir paths differ
            matched = next(
                (v for k, v in per_file.items() if k.endswith(filename)), None
            )
            if matched:
                passed = matched["passed"]
                failed = matched["failed"]
                success = failed == 0
            else:
                passed = total_passed if overall_success else 0
                failed = total_failed if not overall_success else 0
                success = overall_success

            results.append(TestExecutionResult(
                file_path=test.file_path,
                pass_count=passed,
                fail_count=failed,
                success=success,
                error_output="" if success else raw_output[-3000:],
            ))

        return results
