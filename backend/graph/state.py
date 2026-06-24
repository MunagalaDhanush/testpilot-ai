from __future__ import annotations

from typing import TypedDict

from backend.models.schemas import GeneratedTest, TestExecutionResult


class PipelineState(TypedDict, total=False):
    # Job identity
    job_id: str
    pr_url: str
    repo_name: str
    pr_number: int

    # PR content
    diff_content: str
    changed_files: list[str]
    existing_tests: list[str]

    # Risk analysis
    risk_level: str
    risk_score: float

    # Test planning
    test_strategy: dict

    # Generated tests
    generated_tests: list[GeneratedTest]

    # Execution results
    execution_results: list[TestExecutionResult]

    # Self-repair
    repair_attempts: int

    # Summary
    final_summary: str

    # Error accumulation
    errors: list[str]
