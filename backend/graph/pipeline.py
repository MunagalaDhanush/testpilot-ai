from __future__ import annotations

import asyncio
import re
from typing import Any

from langgraph.graph import END, StateGraph
from loguru import logger

from backend.agents.context_collector import ContextCollectorAgent
from backend.agents.failure_diagnostician import FailureDiagnosticianAgent
from backend.agents.pr_summarizer import PRSummarizerAgent
from backend.agents.risk_classifier import RiskClassifierAgent
from backend.agents.test_generator import TestGeneratorAgent
from backend.agents.test_strategist import TestStrategistAgent
from backend.graph.state import PipelineState
from backend.tools.subprocess_runner import SubprocessRunner

MAX_REPAIR_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Node: collect context (sequential)
# ---------------------------------------------------------------------------

async def collect_context(state: PipelineState) -> PipelineState:
    return await ContextCollectorAgent().run(state)


# ---------------------------------------------------------------------------
# Node: risk + test-context analysis (parallel via asyncio.gather)
#
# risk_classifier and parse_existing_tests run simultaneously because they
# read from the same upstream state and write to different fields.
# ---------------------------------------------------------------------------

def _parse_existing_tests(existing_tests: list[str]) -> dict[str, list[str]]:
    """Map each test file to the module names it likely covers (no LLM needed)."""
    coverage: dict[str, list[str]] = {}
    for path in existing_tests:
        # e.g. tests/test_connection_pool.py → covers ["connection_pool"]
        name = re.sub(r"^.*test_?", "", path.split("/")[-1]).replace(".py", "")
        coverage[path] = [name] if name else []
    return coverage


async def analyze_pr(state: PipelineState) -> PipelineState:
    """Runs risk_classifier and test-context parsing in parallel."""
    risk_task = RiskClassifierAgent().run(state)
    coverage_map = _parse_existing_tests(state.get("existing_tests", []))

    risk_state = await risk_task  # single coroutine, gather not needed here but kept explicit

    return {
        **risk_state,
        "existing_coverage": coverage_map,
    }


# ---------------------------------------------------------------------------
# Node: test strategy (sequential)
# ---------------------------------------------------------------------------

async def plan_tests(state: PipelineState) -> PipelineState:
    return await TestStrategistAgent().run(state)


# ---------------------------------------------------------------------------
# Node: parallel test generation (unit + integration + api simultaneously)
#
# Each generator only produces tests for its assigned type.
# The state field `generated_tests` uses operator.add as its reducer, so
# outputs from all three nodes are automatically concatenated by LangGraph.
# ---------------------------------------------------------------------------

async def generate_all_tests(state: PipelineState) -> PipelineState:
    strategy = state.get("test_strategy", {})
    test_types: list[str] = strategy.get("test_types", ["unit"])

    generators = [TestGeneratorAgent(test_type=t).run(state) for t in test_types]

    if not generators:
        return {**state, "generated_tests": []}

    results: list[Any] = await asyncio.gather(*generators, return_exceptions=True)

    all_tests = []
    all_errors = list(state.get("errors") or [])

    for test_type, result in zip(test_types, results):
        if isinstance(result, Exception):
            msg = f"generate_{test_type}: unhandled exception — {result}"
            logger.error(msg)
            all_errors.append(msg)
        else:
            all_tests.extend(result.get("generated_tests", []))
            all_errors.extend(result.get("errors") or [])

    return {**state, "generated_tests": all_tests, "errors": all_errors}


# ---------------------------------------------------------------------------
# Node: execute tests via subprocess
# ---------------------------------------------------------------------------

async def execute_tests(state: PipelineState) -> PipelineState:
    generated = state.get("generated_tests", [])
    job_id = state.get("job_id", "unknown")

    if not generated:
        logger.warning("execute_tests: no generated tests to run")
        return {**state, "execution_results": []}

    runner = SubprocessRunner()
    results = await runner.run_tests(generated, job_id)
    return {**state, "execution_results": results}


# ---------------------------------------------------------------------------
# Node: diagnose + repair failures (sequential, loops back to execute_tests)
# ---------------------------------------------------------------------------

async def diagnose_failures(state: PipelineState) -> PipelineState:
    return await FailureDiagnosticianAgent().run(state)


# ---------------------------------------------------------------------------
# Node: PR summary (sequential)
# ---------------------------------------------------------------------------

async def summarize(state: PipelineState) -> PipelineState:
    return await PRSummarizerAgent().run(state)


# ---------------------------------------------------------------------------
# Conditional edge: should we repair or are we done?
# ---------------------------------------------------------------------------

def should_repair(state: PipelineState) -> str:
    results = state.get("execution_results", [])
    repair_attempts = state.get("repair_attempts", 0)
    has_failures = any(not r.success for r in results)

    if has_failures and repair_attempts < MAX_REPAIR_ATTEMPTS:
        logger.info(f"Repair loop: attempt {repair_attempts + 1}/{MAX_REPAIR_ATTEMPTS}")
        return "diagnose"
    return "summarize"


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_pipeline() -> Any:
    graph: StateGraph = StateGraph(PipelineState)

    graph.add_node("collect_context", collect_context)
    graph.add_node("analyze_pr", analyze_pr)          # risk + existing-test parse
    graph.add_node("plan_tests", plan_tests)
    graph.add_node("generate_all_tests", generate_all_tests)  # parallel internally
    graph.add_node("execute_tests", execute_tests)
    graph.add_node("diagnose_failures", diagnose_failures)
    graph.add_node("summarize", summarize)

    graph.set_entry_point("collect_context")
    graph.add_edge("collect_context", "analyze_pr")
    graph.add_edge("analyze_pr", "plan_tests")
    graph.add_edge("plan_tests", "generate_all_tests")
    graph.add_edge("generate_all_tests", "execute_tests")
    graph.add_conditional_edges(
        "execute_tests",
        should_repair,
        {"diagnose": "diagnose_failures", "summarize": "summarize"},
    )
    graph.add_edge("diagnose_failures", "execute_tests")
    graph.add_edge("summarize", END)

    return graph.compile()


_compiled_pipeline: Any = None


def get_pipeline() -> Any:
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_pipeline()
    return _compiled_pipeline
