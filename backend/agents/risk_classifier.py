from __future__ import annotations

import json

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState

MODEL = "claude-haiku-3-5"

SYSTEM_PROMPT = """You are a risk assessment agent for code changes. Analyze the PR diff and classify the risk.
Return ONLY valid JSON with this shape:
{
  "risk_level": "low|medium|high|critical",
  "risk_score": 0.75,
  "risk_factors": ["modifies auth layer", "no existing tests"],
  "rationale": "one-sentence explanation"
}
Risk guidelines:
- low (0.0-0.3): docs, comments, minor style
- medium (0.3-0.6): new features with tests, refactors in non-critical paths
- high (0.6-0.85): auth, payments, data migration, core business logic
- critical (0.85-1.0): security fixes, production data ops, infra changes"""


class RiskClassifierAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="risk_classifier")

    async def _execute(self, state: PipelineState) -> PipelineState:
        diff = state.get("diff_content", "")
        changed_files = state.get("changed_files", [])
        existing_tests = state.get("existing_tests", [])

        context = (
            f"Changed files: {', '.join(changed_files[:20])}\n"
            f"Existing test files count: {len(existing_tests)}\n\n"
            f"Diff (truncated to 6000 chars):\n{diff[:6000]}"
        )

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": context}],
            system=SYSTEM_PROMPT,
            max_tokens=512,
        )

        try:
            classification = json.loads(text)
            risk_level = classification.get("risk_level", "medium")
            risk_score = float(classification.get("risk_score", 0.5))
        except (json.JSONDecodeError, ValueError):
            logger.warning("Risk classifier returned non-JSON; defaulting to medium")
            risk_level = "medium"
            risk_score = 0.5

        return {
            **state,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "_last_input_tokens": input_tokens,
            "_last_output_tokens": output_tokens,
        }
