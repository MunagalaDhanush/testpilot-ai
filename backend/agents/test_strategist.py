from __future__ import annotations

import json

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState

MODEL = "claude-sonnet-4-5"

SYSTEM_PROMPT = """You are a senior test architect. Given the PR context and risk level, design a test strategy.
Return ONLY valid JSON with this shape:
{
  "test_types": ["unit", "integration"],
  "priority_files": ["src/auth.py", "src/pool.py"],
  "test_cases": [
    {
      "file": "src/auth.py",
      "type": "unit",
      "scenarios": ["happy path login", "invalid credentials", "expired token"],
      "mocking_needed": ["database", "cache"]
    }
  ],
  "coverage_target": 80,
  "rationale": "explanation of strategy"
}
For low risk: unit tests only. For medium: unit + integration. For high/critical: unit + integration + api."""


class TestStrategistAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="test_strategist")

    async def _execute(self, state: PipelineState) -> PipelineState:
        diff = state.get("diff_content", "")
        changed_files = state.get("changed_files", [])
        risk_level = state.get("risk_level", "medium")
        risk_score = state.get("risk_score", 0.5)
        existing_tests = state.get("existing_tests", [])

        context = (
            f"Risk level: {risk_level} (score: {risk_score:.2f})\n"
            f"Changed files: {json.dumps(changed_files[:20])}\n"
            f"Existing test files: {json.dumps(existing_tests[:20])}\n\n"
            f"PR diff (truncated to 8000 chars):\n{diff[:8000]}"
        )

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": context}],
            system=SYSTEM_PROMPT,
            max_tokens=2048,
        )

        try:
            strategy = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Test strategist returned non-JSON; using minimal strategy")
            strategy = {
                "test_types": ["unit"],
                "priority_files": changed_files[:3],
                "test_cases": [],
                "coverage_target": 60,
                "rationale": "Fallback strategy due to parsing error",
            }

        return {
            **state,
            "test_strategy": strategy,
            "_last_input_tokens": input_tokens,
            "_last_output_tokens": output_tokens,
        }
