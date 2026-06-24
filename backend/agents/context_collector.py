from __future__ import annotations

import json
import re

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState
from backend.tools.github_client import GitHubClient

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a code analysis agent. Given a pull request diff, extract structured information.

Return ONLY valid JSON — no markdown fences, no explanation:
{
  "changed_files": ["list of file paths changed"],
  "changed_functions": ["ClassName.method_name or module.function_name"],
  "file_types": ["python", "typescript"],
  "lines_added": 42,
  "lines_removed": 17,
  "change_type": "feature|bugfix|refactor|docs|test|chore",
  "summary": "one-sentence description of what changed"
}

For changed_functions, scan every +/- block and identify function/method definitions.\
"""


class ContextCollectorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="context_collector")

    async def _execute(
        self, state: PipelineState
    ) -> tuple[PipelineState, int, int]:
        repo_name = state.get("repo_name", "")
        pr_number = state.get("pr_number", 0)
        diff = state.get("diff_content", "")
        changed_files: list[str] = []
        existing_tests: list[str] = []

        if not diff and repo_name and pr_number:
            logger.info(f"Fetching PR data for {repo_name}#{pr_number}")
            github = GitHubClient()
            diff = await github.get_pull_request_diff(repo_name, pr_number)
            pr_files = await github.get_pull_request_files(repo_name, pr_number)
            changed_files = [f["filename"] for f in pr_files]
            pr_data = await github.get_pull_request(repo_name, pr_number)
            base_sha = pr_data.get("base", {}).get("sha", "main")
            existing_tests = await github.get_existing_tests(repo_name, base_sha)

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[{"role": "user", "content": f"Analyze this PR diff:\n\n{diff[:8000]}"}],
            system=SYSTEM_PROMPT,
            max_tokens=1024,
        )

        extracted: dict = {}
        try:
            # Strip markdown fences if the model wrapped the JSON anyway
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            extracted = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning("context_collector: JSON parse failed, extracting from diff heuristically")

        if not changed_files:
            changed_files = extracted.get("changed_files", [])

        changed_functions: list[str] = extracted.get("changed_functions", [])

        # Fallback: regex-extract function defs from diff lines if LLM missed them
        if not changed_functions:
            func_pattern = re.compile(r"^\+\s*(?:async\s+)?def\s+(\w+)", re.MULTILINE)
            changed_functions = func_pattern.findall(diff)

        new_state: PipelineState = {
            **state,
            "diff_content": diff,
            "changed_files": changed_files,
            "changed_functions": changed_functions,
            "existing_tests": existing_tests,
        }
        return new_state, input_tokens, output_tokens
