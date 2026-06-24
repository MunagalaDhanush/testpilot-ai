from __future__ import annotations

import json

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.graph.state import PipelineState
from backend.tools.github_client import GitHubClient

MODEL = "claude-haiku-3-5"

SYSTEM_PROMPT = """You are a code analysis agent. Given a pull request diff, extract structured information.
Return ONLY valid JSON with this shape:
{
  "changed_files": ["list", "of", "file", "paths"],
  "languages": ["python", "typescript"],
  "summary": "one-sentence description of what changed",
  "change_type": "feature|bugfix|refactor|docs|test|chore"
}"""


class ContextCollectorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(model_name=MODEL, agent_name="context_collector")

    async def _execute(self, state: PipelineState) -> PipelineState:
        diff = state.get("diff_content", "")
        pr_url = state.get("pr_url", "")
        repo_name = state.get("repo_name", "")
        pr_number = state.get("pr_number", 0)

        if not diff and repo_name and pr_number:
            logger.info(f"Fetching diff for {repo_name}#{pr_number}")
            github = GitHubClient()
            diff = await github.get_pull_request_diff(repo_name, pr_number)
            pr_files = await github.get_pull_request_files(repo_name, pr_number)
            changed_files = [f["filename"] for f in pr_files]

            pr_data = await github.get_pull_request(repo_name, pr_number)
            existing_tests = await github.get_existing_tests(
                repo_name, pr_data.get("base", {}).get("sha", "main")
            )
        else:
            changed_files = []
            existing_tests = state.get("existing_tests", [])

        text, input_tokens, output_tokens = await self._call_llm(
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze this PR diff:\n\n{diff[:8000]}",
                }
            ],
            system=SYSTEM_PROMPT,
            max_tokens=1024,
        )

        try:
            extracted = json.loads(text)
            if not changed_files:
                changed_files = extracted.get("changed_files", [])
        except json.JSONDecodeError:
            logger.warning("Context collector returned non-JSON; using raw diff")
            extracted = {}

        return {
            **state,
            "diff_content": diff,
            "changed_files": changed_files,
            "existing_tests": existing_tests,
            "_last_input_tokens": input_tokens,
            "_last_output_tokens": output_tokens,
        }
