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
    created_at: datetime
    updated_at: datetime
    traces: list[AgentTraceResponse] = Field(default_factory=list)
    generated_tests: list[GeneratedTestResponse] = Field(default_factory=list)


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db_connected: bool
    version: str = "0.1.0"


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
