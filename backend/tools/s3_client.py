from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.exceptions import ClientError
from loguru import logger

from backend.config import get_settings


def _make_s3_client() -> Any:
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_default_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("s3", **kwargs)


class S3Client:
    def __init__(self) -> None:
        self._client = _make_s3_client()
        self._bucket = get_settings().s3_bucket_name
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("404", "NoSuchBucket"):
                self._client.create_bucket(
                    Bucket=self._bucket,
                    CreateBucketConfiguration={"LocationConstraint": get_settings().aws_default_region},
                )
                logger.info(f"Created S3 bucket: {self._bucket}")
            else:
                raise

    def upload_test_file(self, job_id: str, file_path: str, content: str) -> str:
        key = f"jobs/{job_id}/tests/{file_path}"
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/plain",
        )
        logger.debug(f"Uploaded test file to s3://{self._bucket}/{key}")
        return key

    def upload_coverage_report(self, job_id: str, report_data: dict[str, Any]) -> str:
        key = f"jobs/{job_id}/coverage/report.json"
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(report_data).encode("utf-8"),
            ContentType="application/json",
        )
        logger.debug(f"Uploaded coverage report to s3://{self._bucket}/{key}")
        return key

    def upload_execution_results(self, job_id: str, results: dict[str, Any]) -> str:
        key = f"jobs/{job_id}/results/execution.json"
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(results, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        return key

    def download_file(self, key: str) -> str:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read().decode("utf-8")

    def get_presigned_url(self, key: str, expiry_seconds: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expiry_seconds,
        )
