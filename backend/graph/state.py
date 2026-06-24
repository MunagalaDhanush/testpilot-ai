from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from backend.models.schemas import GeneratedTest, TestExecutionResult


class PipelineState(TypedDict, total=False):
    # Job identity
    job_id: str
    pr_url: str
    repo_name: str
    pr_number: int

    # PR content collected by context_collector
    diff_content: str
    changed_files: list[str]
    changed_functions: list[str]
    existing_tests: list[str]
    existing_coverage: dict[str, list[str]]  # test_file → functions it covers

    # Risk analysis from risk_classifier
    risk_level: str
    risk_score: float
    risk_reasons: list[str]

    # Test planning from test_strategist
    test_strategy: dict

    # Generated tests — uses operator.add reducer so parallel generator
    # nodes accumulate into a single list without overwriting each other
    generated_tests: Annotated[list[GeneratedTest], operator.add]

    # Execution results
    execution_results: list[TestExecutionResult]

    # Per-test repair diagnosis from failure_diagnostician
    repair_diagnosis: list[dict]

    # Self-repair loop counter
    repair_attempts: int

    # Final PR comment markdown
    final_summary: str

    # Error accumulation — reducer so parallel nodes can both append
    errors: Annotated[list[str], operator.add]
