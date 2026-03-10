"""S3-compatible storage for claim attachments."""

import uuid
from typing import BinaryIO, cast

from claim_agent.storage.base import StorageAdapter


class S3StorageAdapter(StorageAdapter):
    """Store attachments in S3 or S3-compatible storage (MinIO, etc.)."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "attachments",
        endpoint_url: str | None = None,
    ):
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._endpoint_url = endpoint_url
        self._client_instance = None

    def _client(self):
        if self._client_instance is None:
            import boto3
            from botocore.config import Config

            config = Config(signature_version="s3v4")
            self._client_instance = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                config=config,
            )
        return self._client_instance

    def save(
        self,
        claim_id: str,
        filename: str,
        content: BinaryIO | bytes,
        content_type: str | None = None,
    ) -> str:
        """Upload file to S3, return object key."""
        safe_claim = "".join(c if c.isalnum() or c in "-_" else "_" for c in claim_id)
        safe_name = "".join(c if c.isalnum() or c in ".-_" else "_" for c in filename) or "file"
        unique = uuid.uuid4().hex[:8]
        key = f"{self._prefix}/{safe_claim}/{unique}_{safe_name}"

        data = content.read() if hasattr(content, "read") else content
        extra = {}
        if content_type:
            extra["ContentType"] = content_type

        client = self._client()
        client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            **extra,
        )
        return key

    def get_url(self, claim_id: str, stored_path_or_key: str) -> str:
        """Return presigned URL or public URL for S3 object."""
        key = stored_path_or_key
        client = self._client()
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=3600 * 24 * 7,  # 7 days
        )
        return cast(str, url)

    def exists(self, claim_id: str, stored_path_or_key: str) -> bool:
        """Check if object exists in S3."""
        try:
            client = self._client()
            client.head_object(Bucket=self._bucket, Key=stored_path_or_key)
            return True
        except Exception:
            return False
