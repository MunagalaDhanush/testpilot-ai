from __future__ import annotations

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState
from backend.models.schemas import TestExecutionResult

MODEL = "claude-haiku-3-5"

SYSTEM_PROMPT = """You are a technical writer producing PR test summaries for GitHub comments.
Write a concise, engineer-friendly markdown summary. Include:
- What risk level was detected and why
- What tests were generated (counts, types)
- Test execution results (pass/fail counts)
- Whether any repairs were needed
- A "TestPilot AI" footer line

Keep it under 400 words. Use emojis sparingly for status indicators (✅ ❌ ⚠️)."""


class PRSummarizerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="pr_summarizer")

    async def _execute(self, state: PipelineState) -> PipelineState:
        risk_level = state.get("risk_level", "unknown")
        risk_score = state.get("risk_score", 0.0)
        strategy = state.get("test_strategy", {})
        generated_tests = state.get("generated_tests", [])
        execution_results: list[TestExecutionResult] = state.get("execution_results", [])
        repair_attempts = state.get("repair_attempts", 0)
        errors = state.get("errors", [])
        pr_url = state.get("pr_url", "")

        total_pass = sum(r.pass_count for r in execution_results)
        total_fail = sum(r.fail_count for r in execution_results)
        all_passed = all(r.success for r in execution_results) if execution_results else False

        context = f"""PR URL: {pr_url}
Risk level: {risk_level} (score: {risk_score:.2f})
Strategy rationale: {strategy.get('rationale', 'N/A')}
Tests generated: {len(generated_tests)} file(s) — types: {', '.join(set(t.test_type for t in generated_tests))}
Execution: {total_pass} passed, {total_fail} failed
All tests passing: {all_passed}
Repair attempts: {repair_attempts}
Errors during pipeline: {errors if errors else 'none'}"""

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": context}],
            system=SYSTEM_PROMPT,
            max_tokens=1024,
        )

        return {
            **state,
            "final_summary": text,
            "_last_input_tokens": input_tokens,
            "_last_output_tokens": output_tokens,
        }
