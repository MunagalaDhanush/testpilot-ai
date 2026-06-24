from __future__ import annotations

import json
import re

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a risk assessment agent for code changes.

Analyze the PR diff and classify its risk level. Consider:
- Authentication or authorization changes
- Payment or financial logic
- Data mutations or migrations
- API contract changes (adding/removing/renaming fields)
- Security implications (input validation, secrets, permissions)
- Critical path code with no existing test coverage

Return ONLY valid JSON — no markdown fences:
{
  "risk_level": "low|medium|high|critical",
  "risk_score": 72,
  "risk_reasons": [
    "Modifies JWT validation logic",
    "No existing tests for this module"
  ],
  "rationale": "one-sentence explanation"
}

Risk score is 0-100. Guidelines:
  low      0-30  : docs, comments, minor style, test-only changes
  medium  31-60  : new features with tests, refactors in non-critical paths
  high    61-85  : auth, payments, data migration, core business logic
  critical 86-100: security hotfixes, prod data ops, infra changes\
"""


class RiskClassifierAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="risk_classifier")

    async def _execute(
        self, state: PipelineState
    ) -> tuple[PipelineState, int, int]:
        diff = state.get("diff_content", "")
        changed_files = state.get("changed_files", [])
        changed_functions = state.get("changed_functions", [])
        existing_tests = state.get("existing_tests", [])

        context = (
            f"Changed files: {', '.join(changed_files[:20])}\n"
            f"Changed functions: {', '.join(changed_functions[:20])}\n"
            f"Existing test files count: {len(existing_tests)}\n\n"
            f"Diff (first 6000 chars):\n{diff[:6000]}"
        )

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": context}],
            system=SYSTEM_PROMPT,
            max_tokens=768,
        )

        risk_level = "medium"
        risk_score = 50.0
        risk_reasons: list[str] = []
        try:
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            data = json.loads(clean)
            risk_level = data.get("risk_level", "medium")
            risk_score = float(data.get("risk_score", 50))
            risk_reasons = data.get("risk_reasons", [])
        except (json.JSONDecodeError, ValueError):
            logger.warning("risk_classifier: JSON parse failed, defaulting to medium")

        return (
            {**state, "risk_level": risk_level, "risk_score": risk_score, "risk_reasons": risk_reasons},
            input_tokens,
            output_tokens,
        )
