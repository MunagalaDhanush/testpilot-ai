from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from anthropic import AsyncAnthropic, APIError, APITimeoutError
from langfuse import Langfuse
from loguru import logger

from backend.config import get_settings
from backend.db.connection import get_pool
from backend.graph.state import PipelineState


class BaseAgent(ABC):
    def __init__(self, model_name: str, agent_name: str) -> None:
        self.model_name = model_name
        self.agent_name = agent_name
        settings = get_settings()
        self._anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )

    @abstractmethod
    async def _execute(self, state: PipelineState) -> PipelineState:
        """Agent-specific logic. Must return the updated state."""

    async def run(self, state: PipelineState) -> PipelineState:
        job_id = state.get("job_id", "unknown")
        log = logger.bind(agent=self.agent_name, job_id=job_id, model=self.model_name)
        log.info("Starting agent")

        trace = self._langfuse.trace(
            name=self.agent_name,
            metadata={"job_id": job_id, "model": self.model_name},
        )
        span = trace.span(name="run")

        start_ms = time.monotonic_ns() // 1_000_000
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                result_state = await self._execute(state)
                elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms
                span.end(metadata={"attempt": attempt, "latency_ms": elapsed_ms})
                await self._save_trace(
                    job_id=job_id,
                    input_tokens=result_state.get("_last_input_tokens"),
                    output_tokens=result_state.get("_last_output_tokens"),
                    latency_ms=elapsed_ms,
                )
                log.info(f"Agent completed in {elapsed_ms}ms")
                return result_state

            except (APIError, APITimeoutError) as e:
                last_error = e
                wait = 2 ** attempt
                log.warning(f"Attempt {attempt}/3 failed ({type(e).__name__}), retrying in {wait}s")
                if attempt < 3:
                    await asyncio.sleep(wait)

        elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms
        span.end(metadata={"failed": True, "latency_ms": elapsed_ms})
        error_msg = f"{self.agent_name} failed after 3 attempts: {last_error}"
        log.error(error_msg)
        errors = list(state.get("errors") or [])
        errors.append(error_msg)
        return {**state, "errors": errors}

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> tuple[str, int, int]:
        """Call Anthropic and return (text, input_tokens, output_tokens)."""
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = await self._anthropic.messages.create(**kwargs)
        text = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        return text, input_tokens, output_tokens

    async def _save_trace(
        self,
        job_id: str,
        input_tokens: int | None,
        output_tokens: int | None,
        latency_ms: int,
    ) -> None:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_traces
                        (job_id, agent_name, model_used, input_tokens, output_tokens, latency_ms)
                    VALUES ($1::uuid, $2, $3, $4, $5, $6)
                    """,
                    job_id,
                    self.agent_name,
                    self.model_name,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                )
        except Exception as e:
            logger.warning(f"Failed to save agent trace: {e}")
