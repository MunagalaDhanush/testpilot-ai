from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str

    # GitHub
    github_token: str
    github_webhook_secret: str

    # Langfuse
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str = "https://cloud.langfuse.com"

    # Database
    database_url: str

    # AWS / LocalStack
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_default_region: str = "us-east-2"
    aws_endpoint_url: str | None = None

    # SQS
    sqs_queue_name: str = "testpilot-jobs"
    sqs_queue_url: str

    # S3
    s3_bucket_name: str = "testpilot-artifacts"

    # n8n
    n8n_webhook_url: str = ""  # e.g. http://n8n:5678/webhook/testpilot

    # App
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://localhost:8000"

    @field_validator("anthropic_api_key")
    @classmethod
    def anthropic_key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("ANTHROPIC_API_KEY must be set (even a placeholder for local dev)")
        return v

    @field_validator("github_token")
    @classmethod
    def github_token_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("GITHUB_TOKEN must be set (even a placeholder for local dev)")
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_local(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
