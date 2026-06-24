from __future__ import annotations

from langgraph.graph import END, StateGraph

from backend.agents.context_collector import ContextCollectorAgent
from backend.agents.failure_diagnostician import FailureDiagnosticianAgent
from backend.agents.pr_summarizer import PRSummarizerAgent
from backend.agents.risk_classifier import RiskClassifierAgent
from backend.agents.test_generator import TestGeneratorAgent
from backend.agents.test_strategist import TestStrategistAgent
from backend.graph.state import PipelineState
from backend.tools.docker_runner import DockerRunner
from backend.tools.s3_client import S3Client

MAX_REPAIR_ATTEMPTS = 3


async def collect_context(state: PipelineState) -> PipelineState:
    return await ContextCollectorAgent().run(state)


async def classify_risk(state: PipelineState) -> PipelineState:
    return await RiskClassifierAgent().run(state)


async def plan_tests(state: PipelineState) -> PipelineState:
    return await TestStrategistAgent().run(state)


async def generate_tests(state: PipelineState) -> PipelineState:
    return await TestGeneratorAgent().run(state)


async def execute_tests(state: PipelineState) -> PipelineState:
    generated = state.get("generated_tests", [])
    job_id = state.get("job_id", "unknown")

    if not generated:
        return {**state, "execution_results": []}

    runner = DockerRunner()
    results = runner.run_tests(generated, job_id)

    s3 = S3Client()
    s3.upload_execution_results(job_id, [r.model_dump() for r in results])

    return {**state, "execution_results": results}


async def diagnose_failures(state: PipelineState) -> PipelineState:
    return await FailureDiagnosticianAgent().run(state)


async def summarize(state: PipelineState) -> PipelineState:
    return await PRSummarizerAgent().run(state)


def should_repair(state: PipelineState) -> str:
    results = state.get("execution_results", [])
    repair_attempts = state.get("repair_attempts", 0)
    has_failures = any(not r.success for r in results)

    if has_failures and repair_attempts < MAX_REPAIR_ATTEMPTS:
        return "diagnose"
    return "summarize"


def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("collect_context", collect_context)
    graph.add_node("classify_risk", classify_risk)
    graph.add_node("plan_tests", plan_tests)
    graph.add_node("generate_tests", generate_tests)
    graph.add_node("execute_tests", execute_tests)
    graph.add_node("diagnose_failures", diagnose_failures)
    graph.add_node("summarize", summarize)

    graph.set_entry_point("collect_context")
    graph.add_edge("collect_context", "classify_risk")
    graph.add_edge("classify_risk", "plan_tests")
    graph.add_edge("plan_tests", "generate_tests")
    graph.add_edge("generate_tests", "execute_tests")
    graph.add_conditional_edges(
        "execute_tests",
        should_repair,
        {"diagnose": "diagnose_failures", "summarize": "summarize"},
    )
    graph.add_edge("diagnose_failures", "execute_tests")
    graph.add_edge("summarize", END)

    return graph.compile()


_compiled_pipeline = None


def get_pipeline():
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_pipeline()
    return _compiled_pipeline
