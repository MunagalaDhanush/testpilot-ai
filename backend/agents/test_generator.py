from __future__ import annotations

import json
import re

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState
from backend.models.schemas import GeneratedTest

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You are an expert test engineer. Generate complete, immediately runnable Python pytest test files.

Rules:
- Every test file must be self-contained with all imports at the top
- Use pytest fixtures for setup/teardown; use @pytest.mark.asyncio for async tests
- Mock ALL external dependencies (DB, HTTP, file I/O) using unittest.mock.patch or pytest-mock
- Test names must be descriptive: test_<function>_<scenario>
- Cover every scenario in the test_cases list: positive, negative, and edge cases
- Do NOT write placeholder comments — every test must have a real assertion
- Generated tests should work with `pytest <file> -v` without any extra setup

Return ONLY valid JSON — no markdown fences:
{
  "tests": [
    {
      "file_path": "tests/test_connection_pool.py",
      "test_type": "unit",
      "functions_covered": ["ConnectionPool.release", "ConnectionPool.close_all"],
      "content": "import pytest\\nfrom unittest.mock import MagicMock, patch\\n\\n..."
    }
  ]
}\
"""


class TestGeneratorAgent(BaseAgent):
    def __init__(self, test_type: str = "unit") -> None:
        super().__init__(model_name=MODEL, agent_name=f"test_generator_{test_type}")
        self._test_type = test_type

    async def _execute(
        self, state: PipelineState
    ) -> tuple[PipelineState, int, int]:
        diff = state.get("diff_content", "")
        strategy = state.get("test_strategy", {})
        risk_level = state.get("risk_level", "medium")

        # Only pick test cases that match our assigned type
        all_cases = strategy.get("test_cases", [])
        my_cases = [c for c in all_cases if c.get("test_type") == self._test_type]

        if not my_cases:
            logger.info(f"test_generator_{self._test_type}: no cases assigned, skipping")
            return {**state, "generated_tests": []}, 0, 0

        context = (
            f"Risk level: {risk_level}\n"
            f"Test type to generate: {self._test_type}\n"
            f"Test cases:\n{json.dumps(my_cases, indent=2)}\n\n"
            f"PR diff (source context, first 10000 chars):\n{diff[:10000]}"
        )

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": context}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
        )

        generated: list[GeneratedTest] = []
        try:
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            parsed = json.loads(clean)
            for t in parsed.get("tests", []):
                generated.append(GeneratedTest(
                    file_path=t["file_path"],
                    test_type=t.get("test_type", self._test_type),
                    file_content=t["content"],
                ))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"test_generator_{self._test_type}: JSON parse failed ({e}), "
                           "falling back to code-block extraction")
            for i, block in enumerate(re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)):
                generated.append(GeneratedTest(
                    file_path=f"tests/test_{self._test_type}_generated_{i}.py",
                    test_type=self._test_type,
                    file_content=block.strip(),
                ))

        if not generated:
            logger.error(f"test_generator_{self._test_type}: produced no tests")
            return (
                {**state, "generated_tests": [], "errors": [f"test_generator_{self._test_type}: no tests produced"]},
                input_tokens,
                output_tokens,
            )

        logger.info(f"test_generator_{self._test_type}: generated {len(generated)} file(s)")
        # The state reducer (operator.add) merges this with outputs from the
        # other parallel generator nodes
        return {**state, "generated_tests": generated}, input_tokens, output_tokens
