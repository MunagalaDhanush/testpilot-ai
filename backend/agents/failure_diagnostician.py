from __future__ import annotations

import json
import re

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState
from backend.models.schemas import GeneratedTest, TestExecutionResult

MODEL = "claude-sonnet-4-5"

SYSTEM_PROMPT = """You are a test debugging expert. Given failing test output, diagnose and fix the tests.
Return ONLY valid JSON:
{
  "fixed_tests": [
    {
      "file_path": "tests/test_pool.py",
      "test_type": "unit",
      "content": "...corrected test code...",
      "fix_explanation": "what was wrong and what was changed"
    }
  ]
}
Common issues to check:
- Wrong import paths for the module under test
- Missing mock patches for external dependencies
- Incorrect assertions (wrong type, wrong value)
- Async test missing @pytest.mark.asyncio
- Missing fixture setup/teardown"""


class FailureDiagnosticianAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="failure_diagnoser")

    async def _execute(self, state: PipelineState) -> PipelineState:
        generated_tests: list[GeneratedTest] = state.get("generated_tests", [])
        execution_results: list[TestExecutionResult] = state.get("execution_results", [])
        diff = state.get("diff_content", "")
        repair_attempts = state.get("repair_attempts", 0)

        failing = [r for r in execution_results if not r.success]
        if not failing:
            logger.info("No failures to diagnose")
            return state

        failure_context_parts: list[str] = []
        for result in failing:
            matching_test = next(
                (t for t in generated_tests if t.file_path == result.file_path), None
            )
            if matching_test:
                failure_context_parts.append(
                    f"=== FAILING FILE: {result.file_path} ===\n"
                    f"Error output:\n{result.error_output[:2000]}\n\n"
                    f"Current test code:\n{matching_test.file_content[:3000]}"
                )

        context = (
            f"Repair attempt: {repair_attempts + 1}/3\n"
            f"PR diff (for context):\n{diff[:4000]}\n\n"
            + "\n\n".join(failure_context_parts[:3])
        )

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": context}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
        )

        try:
            parsed = json.loads(text)
            fixed_tests_raw = parsed.get("fixed_tests", [])
        except json.JSONDecodeError:
            logger.warning("Failure diagnostician returned non-JSON; attempting extraction")
            code_blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
            fixed_tests_raw = [
                {"file_path": f.file_path, "test_type": f.test_type, "content": block.strip()}
                for f, block in zip(failing[:len(code_blocks)], code_blocks)
            ]

        repaired: list[GeneratedTest] = []
        for item in fixed_tests_raw:
            repaired.append(
                GeneratedTest(
                    file_path=item.get("file_path", "tests/test_repaired.py"),
                    test_type=item.get("test_type", "unit"),
                    file_content=item.get("content", ""),
                )
            )

        updated_tests = list(generated_tests)
        for repaired_test in repaired:
            for i, t in enumerate(updated_tests):
                if t.file_path == repaired_test.file_path:
                    updated_tests[i] = repaired_test
                    break
            else:
                updated_tests.append(repaired_test)

        return {
            **state,
            "generated_tests": updated_tests,
            "repair_attempts": repair_attempts + 1,
            "_last_input_tokens": input_tokens,
            "_last_output_tokens": output_tokens,
        }
