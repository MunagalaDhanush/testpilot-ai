from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    pr_url: str
    repo_name: str
    pr_number: int
    pr_title: str | None = None
    diff_content: str | None = None


class AgentTraceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    agent_name: str
    model_used: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    created_at: datetime


class GeneratedTestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    test_type: str
    file_content: str
    file_path: str
    pass_count: int
    fail_count: int
    coverage_delta: float
    repair_attempts: int
    created_at: datetime


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pr_url: str
    repo_name: str
    pr_number: int
    pr_title: str | None
    diff_content: str | None
    status: str
    risk_level: str | None
    final_summary: str | None = None
    tests_generated: int = 0
    pass_count: int = 0
    fail_count: int = 0
    coverage_delta: float = 0.0
    human_approved: bool | None = None
    human_reviewed_at: datetime | None = None
    source: str = "webhook"
    created_at: datetime
    updated_at: datetime
    traces: list[AgentTraceResponse] = Field(default_factory=list)
    generated_tests: list[GeneratedTestResponse] = Field(default_factory=list)


class JobListStats(BaseModel):
    total_tests_generated: int = 0
    avg_pass_rate: float | None = None
    avg_coverage_delta: float | None = None


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int
    stats: JobListStats = Field(default_factory=JobListStats)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db_connected: bool
    version: str = "0.1.0"


class SystemStatusResponse(BaseModel):
    paused: bool
    stopped: bool = False
    active: bool = True
    active_jobs: int
    queued_jobs: int
    awaiting_review: int


class AnalyticsPassRatePoint(BaseModel):
    date: str
    pass_rate: float
    total_jobs: int


class AnalyticsAgentPerf(BaseModel):
    agent_name: str
    model_used: str
    avg_latency_ms: int
    run_count: int


class AnalyticsModelTokens(BaseModel):
    job_id: str
    date: str
    haiku_tokens: int
    sonnet_tokens: int


class AnalyticsRiskItem(BaseModel):
    risk_level: str
    count: int


class AnalyticsResponse(BaseModel):
    pass_rate_over_time: list[AnalyticsPassRatePoint]
    risk_distribution: list[AnalyticsRiskItem]
    agent_performance: list[AnalyticsAgentPerf]
    model_tokens_per_job: list[AnalyticsModelTokens]


class AnalyzeJobRequest(BaseModel):
    pr_url: str | None = None
    diff_content: str | None = None
    repo_name: str
    pr_number: int | None = None


class WebhookGitHubPayload(BaseModel):
    """Payload forwarded by n8n from GitHub PR webhook."""

    action: str
    pull_request: dict
    repository: dict
    sender: dict | None = None

    @property
    def pr_url(self) -> str:
        return self.pull_request["html_url"]

    @property
    def repo_name(self) -> str:
        return self.repository["full_name"]

    @property
    def pr_number(self) -> int:
        return self.pull_request["number"]

    @property
    def pr_title(self) -> str:
        return self.pull_request.get("title", "")


class GeneratedTest(BaseModel):
    test_type: Literal["unit", "integration", "api"]
    file_content: str
    file_path: str


class TestExecutionResult(BaseModel):
    file_path: str
    pass_count: int = 0
    fail_count: int = 0
    coverage_delta: float = 0.0
    error_output: str = ""
    success: bool = False
