from __future__ import annotations

import json
import re

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState
from backend.models.schemas import GeneratedTest

MODEL = "claude-sonnet-4-5"

SYSTEM_PROMPT = """You are an expert test engineer. Generate complete, runnable Python pytest test files.
Rules:
- Write complete, self-contained test files with all imports
- Use pytest and pytest-asyncio for async tests
- Mock external dependencies with unittest.mock or pytest-mock
- Include docstrings explaining each test's intent
- Do NOT use placeholder comments like "add logic here"
- Return ONLY valid JSON with this shape:
{
  "tests": [
    {
      "file_path": "tests/test_pool.py",
      "test_type": "unit",
      "content": "import pytest\\n\\ndef test_something():\\n    pass"
    }
  ]
}"""


class TestGeneratorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="test_generator")

    async def _execute(self, state: PipelineState) -> PipelineState:
        diff = state.get("diff_content", "")
        strategy = state.get("test_strategy", {})
        changed_files = state.get("changed_files", [])
        risk_level = state.get("risk_level", "medium")

        test_cases = strategy.get("test_cases", [])
        test_types = strategy.get("test_types", ["unit"])

        context = (
            f"Risk level: {risk_level}\n"
            f"Test types to generate: {', '.join(test_types)}\n"
            f"Test cases to implement:\n{json.dumps(test_cases, indent=2)}\n\n"
            f"PR diff:\n{diff[:10000]}"
        )

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": context}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
        )

        generated: list[GeneratedTest] = []
        try:
            parsed = json.loads(text)
            for t in parsed.get("tests", []):
                generated.append(
                    GeneratedTest(
                        file_path=t["file_path"],
                        test_type=t.get("test_type", "unit"),
                        file_content=t["content"],
                    )
                )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Test generator JSON parse failed ({e}); attempting code extraction")
            code_blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
            for i, block in enumerate(code_blocks):
                generated.append(
                    GeneratedTest(
                        file_path=f"tests/test_generated_{i}.py",
                        test_type="unit",
                        file_content=block.strip(),
                    )
                )

        if not generated:
            logger.error("Test generator produced no tests")
            errors = list(state.get("errors") or [])
            errors.append("test_generator: no tests produced")
            return {**state, "generated_tests": [], "errors": errors}

        logger.info(f"Generated {len(generated)} test file(s)")
        return {
            **state,
            "generated_tests": generated,
            "_last_input_tokens": input_tokens,
            "_last_output_tokens": output_tokens,
        }
