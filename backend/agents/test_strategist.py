from __future__ import annotations

import json
import re

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You are a senior test architect. Given PR context and risk analysis, design a precise test strategy.

Return ONLY valid JSON — no markdown fences:
{
  "test_types": ["unit", "integration"],
  "coverage_target": 85,
  "rationale": "why these test types were chosen",
  "test_cases": [
    {
      "function_to_test": "ConnectionPool.release",
      "test_type": "unit",
      "priority": "high",
      "expected_coverage_gain": 15,
      "scenarios": [
        {
          "name": "release_within_capacity",
          "description": "Connection released when pool not at max",
          "kind": "positive"
        },
        {
          "name": "release_at_capacity_closes_connection",
          "description": "Connection is closed when pool already full",
          "kind": "negative"
        },
        {
          "name": "release_with_zero_max_size",
          "description": "Edge case: max_size=0 closes every connection",
          "kind": "edge"
        }
      ],
      "mocking_needed": ["connection.close"]
    }
  ]
}

Test type selection rules:
  low risk   → unit only
  medium     → unit + integration
  high/critical → unit + integration + api

Priority rules:
  high   → auth, payments, data mutations, public API surface
  medium → business logic, utilities
  low    → helpers, formatters, minor changes\
"""


class TestStrategistAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="test_strategist")

    async def _execute(
        self, state: PipelineState
    ) -> tuple[PipelineState, int, int]:
        diff = state.get("diff_content", "")
        changed_files = state.get("changed_files", [])
        changed_functions = state.get("changed_functions", [])
        risk_level = state.get("risk_level", "medium")
        risk_score = state.get("risk_score", 50.0)
        risk_reasons = state.get("risk_reasons", [])
        existing_tests = state.get("existing_tests", [])

        context = (
            f"Risk level: {risk_level} (score: {risk_score:.0f}/100)\n"
            f"Risk reasons: {', '.join(risk_reasons) or 'none identified'}\n"
            f"Changed files: {json.dumps(changed_files[:20])}\n"
            f"Changed functions: {json.dumps(changed_functions[:20])}\n"
            f"Existing test files: {json.dumps(existing_tests[:20])}\n\n"
            f"PR diff (first 8000 chars):\n{diff[:8000]}"
        )

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": context}],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
        )

        try:
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            strategy = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning("test_strategist: JSON parse failed, using minimal fallback strategy")
            strategy = {
                "test_types": ["unit"],
                "coverage_target": 60,
                "rationale": "Fallback strategy — JSON parse error",
                "test_cases": [
                    {
                        "function_to_test": f,
                        "test_type": "unit",
                        "priority": "medium",
                        "expected_coverage_gain": 5,
                        "scenarios": [
                            {"name": "happy_path", "description": "Basic positive case", "kind": "positive"}
                        ],
                        "mocking_needed": [],
                    }
                    for f in (changed_functions or ["unknown_function"])[:3]
                ],
            }

        return {**state, "test_strategy": strategy}, input_tokens, output_tokens
