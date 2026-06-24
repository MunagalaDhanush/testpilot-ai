from __future__ import annotations

import json
import re

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState
from backend.models.schemas import GeneratedTest, TestExecutionResult

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You are a test debugging expert. Diagnose failing pytest output and produce corrected test files.

Failure taxonomy — identify the category for each failing test:
  IMPORT_ERROR   → module not found or circular import; fix import paths and mock the module
  ASSERTION_ERROR→ assertion value mismatch; revise expected values or fix the logic under test
  MOCK_FAILURE   → mock not patching the right target; rebuild the mock with correct dotted path
  TIMEOUT        → test takes too long; simplify scope, reduce loops, stub slow I/O
  SYNTAX_ERROR   → invalid Python; direct correction pass
  FLAKY          → passes sometimes, fails sometimes; add @pytest.mark.flaky or retry logic

Return ONLY valid JSON — no markdown fences:
{
  "diagnoses": [
    {
      "file_path": "tests/test_pool.py",
      "failure_category": "MOCK_FAILURE",
      "root_cause": "patch target was 'pool.Connection' but import is 'src.pool.Connection'",
      "fix_explanation": "Changed patch target to correct dotted path"
    }
  ],
  "fixed_tests": [
    {
      "file_path": "tests/test_pool.py",
      "test_type": "unit",
      "content": "import pytest\\n..."
    }
  ]
}\
"""


class FailureDiagnosticianAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="failure_diagnoser")

    async def _execute(
        self, state: PipelineState
    ) -> tuple[PipelineState, int, int]:
        generated_tests: list[GeneratedTest] = state.get("generated_tests", [])
        execution_results: list[TestExecutionResult] = state.get("execution_results", [])
        diff = state.get("diff_content", "")
        repair_attempts = state.get("repair_attempts", 0)

        failing = [r for r in execution_results if not r.success]
        if not failing:
            logger.info("failure_diagnoser: no failures to diagnose")
            return state, 0, 0

        # Build context for each failing test (cap at 3 to stay within token budget)
        parts: list[str] = []
        for result in failing[:3]:
            matching = next((t for t in generated_tests if t.file_path == result.file_path), None)
            if matching:
                parts.append(
                    f"=== FAILING: {result.file_path} ===\n"
                    f"--- pytest output ---\n{result.error_output[:2500]}\n\n"
                    f"--- current test code ---\n{matching.file_content[:3000]}"
                )

        context = (
            f"Repair attempt {repair_attempts + 1}/3\n"
            f"PR diff for reference:\n{diff[:3000]}\n\n"
            + "\n\n".join(parts)
        )

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": context}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
        )

        fixed_raw: list[dict] = []
        diagnoses: list[dict] = []
        try:
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            parsed = json.loads(clean)
            fixed_raw = parsed.get("fixed_tests", [])
            diagnoses = parsed.get("diagnoses", [])
        except json.JSONDecodeError:
            logger.warning("failure_diagnoser: JSON parse failed, extracting code blocks")
            for result, block in zip(
                failing,
                re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL),
            ):
                fixed_raw.append({
                    "file_path": result.file_path,
                    "test_type": "unit",
                    "content": block.strip(),
                })

        # Merge repaired tests back — replace matching file_path, append new ones
        updated = list(generated_tests)
        for item in fixed_raw:
            repaired = GeneratedTest(
                file_path=item.get("file_path", "tests/test_repaired.py"),
                test_type=item.get("test_type", "unit"),
                file_content=item.get("content", ""),
            )
            for i, t in enumerate(updated):
                if t.file_path == repaired.file_path:
                    updated[i] = repaired
                    break
            else:
                updated.append(repaired)

        return (
            {
                **state,
                "generated_tests": updated,
                "repair_diagnosis": diagnoses,
                "repair_attempts": repair_attempts + 1,
            },
            input_tokens,
            output_tokens,
        )
