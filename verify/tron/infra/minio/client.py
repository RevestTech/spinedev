"""
MinIO object storage client for audit artifacts (repo snapshots, LLM logs, findings).

All artifacts are stored in S3-compatible MinIO with paths organized by audit run:
    {bucket}/audits/{audit_run_id}/artifact_name

MinIO credentials (user, password) come from keyvault at runtime.
The minio Python package is synchronous, so all I/O is wrapped with asyncio.to_thread()
to maintain the async interface.

Usage:
    from tron.infra.minio import get_minio_client

    client = await get_minio_client()
    path = await client.upload_artifact(
        audit_run_id=UUID(...),
        artifact_name="repo_snapshot.tar.gz",
        data=b"...",
        content_type="application/gzip",
    )
    data = await client.download_artifact(path)
    artifacts = await client.list_artifacts(audit_run_id=UUID(...))
    deleted = await client.delete_artifacts(audit_run_id=UUID(...))
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Optional
from uuid import UUID

from minio import Minio
from minio.error import S3Error

from tron.infra.secrets import get_secrets

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "tron-artifacts")
MINIO_SECURE = os.getenv("MINIO_SECURE", "true").lower() == "true"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class ArtifactInfo:
    """Metadata about an artifact stored in MinIO."""
    path: str
    size_bytes: int
    content_type: str
    last_modified: datetime


# ---------------------------------------------------------------------------
# MinIO Client
# ---------------------------------------------------------------------------

class MinIOClient:
    """
    Async MinIO client for storing audit artifacts.

    All artifact paths follow the convention:
        audits/{audit_run_id}/{artifact_name}

    The underlying minio library is synchronous, so all I/O operations
    are executed via asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = True,
    ) -> None:
        """
        Initialize the MinIO client.

        Args:
            endpoint: MinIO server endpoint (e.g., "minio:9000")
            access_key: Access key (username)
            secret_key: Secret key (password)
            bucket: Default bucket name
            secure: Use HTTPS/TLS
        """
        self.endpoint = endpoint
        self.bucket = bucket
        self.secure = secure

        self._client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

        logger.info(
            "MinIOClient initialized (endpoint=%s, bucket=%s, secure=%s)",
            endpoint,
            bucket,
            secure,
        )

    async def ensure_bucket(self) -> None:
        """
        Create the bucket if it doesn't exist.

        Called during initialization to verify bucket availability.
        """
        try:
            result = await asyncio.to_thread(
                self._client.bucket_exists, self.bucket
            )
            if not result:
                logger.info("Bucket '%s' does not exist. Creating...", self.bucket)
                await asyncio.to_thread(
                    self._client.make_bucket, self.bucket
                )
                logger.info("Bucket '%s' created successfully", self.bucket)
            else:
                logger.info("Bucket '%s' exists", self.bucket)
        except S3Error as e:
            raise RuntimeError(
                f"Failed to ensure bucket '{self.bucket}': {e}"
            ) from e

    async def upload_artifact(
        self,
        audit_run_id: UUID,
        artifact_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload an artifact to MinIO.

        Args:
            audit_run_id: UUID of the audit run (used in path)
            artifact_name: Name of the artifact (e.g., "repo_snapshot.tar.gz")
            data: Binary data to upload
            content_type: MIME type of the artifact

        Returns:
            The object path: "audits/{audit_run_id}/{artifact_name}"

        Raises:
            RuntimeError: If upload fails
        """
        object_path = self._build_path(audit_run_id, artifact_name)

        try:
            # Wrap bytes in BytesIO for minio.put_object
            stream = BytesIO(data)

            await asyncio.to_thread(
                self._client.put_object,
                self.bucket,
                object_path,
                stream,
                length=len(data),
                content_type=content_type,
            )

            logger.info(
                "Artifact uploaded: %s (size=%d bytes, content_type=%s)",
                object_path,
                len(data),
                content_type,
            )
            return object_path

        except S3Error as e:
            raise RuntimeError(
                f"Failed to upload artifact '{object_path}': {e}"
            ) from e

    async def download_artifact(self, object_path: str) -> bytes:
        """
        Download an artifact from MinIO.

        Args:
            object_path: The full path to the artifact (e.g., "audits/{uuid}/{name}")

        Returns:
            The artifact data as bytes

        Raises:
            RuntimeError: If download fails or artifact does not exist
        """
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                self.bucket,
                object_path,
            )
            data = await asyncio.to_thread(response.read)
            await asyncio.to_thread(response.close)
            logger.debug("Artifact downloaded: %s (size=%d bytes)", object_path, len(data))
            return data
        except S3Error as e:
            raise RuntimeError(
                f"Failed to download artifact '{object_path}': {e}"
            ) from e

    async def list_artifacts(self, audit_run_id: UUID) -> list[ArtifactInfo]:
        """
        List all artifacts for a given audit run.

        Args:
            audit_run_id: UUID of the audit run

        Returns:
            List of ArtifactInfo objects, sorted by last_modified (newest first)

        Raises:
            RuntimeError: If listing fails
        """
        prefix = f"audits/{audit_run_id}/"

        try:
            objects = await asyncio.to_thread(
                self._client.list_objects,
                self.bucket,
                prefix=prefix,
            )

            artifacts: list[ArtifactInfo] = []
            for obj in objects:
                artifacts.append(
                    ArtifactInfo(
                        path=obj.object_name,
                        size_bytes=obj.size,
                        content_type=obj.metadata.get("Content-Type")
                        if obj.metadata
                        else "application/octet-stream",
                        last_modified=obj.last_modified,
                    )
                )

            # Sort by last_modified descending (newest first)
            artifacts.sort(key=lambda a: a.last_modified, reverse=True)

            logger.debug(
                "Listed %d artifacts for audit_run %s",
                len(artifacts),
                audit_run_id,
            )
            return artifacts

        except S3Error as e:
            raise RuntimeError(
                f"Failed to list artifacts for audit_run {audit_run_id}: {e}"
            ) from e

    async def delete_artifacts(self, audit_run_id: UUID) -> int:
        """
        Delete all artifacts for a given audit run (GDPR/compliance).

        Args:
            audit_run_id: UUID of the audit run

        Returns:
            Number of artifacts deleted

        Raises:
            RuntimeError: If deletion fails
        """
        prefix = f"audits/{audit_run_id}/"

        try:
            # List all objects with the prefix
            objects = await asyncio.to_thread(
                self._client.list_objects,
                self.bucket,
                prefix=prefix,
            )

            object_names = [obj.object_name for obj in objects]

            # Delete objects in bulk
            if object_names:
                await asyncio.to_thread(
                    self._client.remove_objects,
                    self.bucket,
                    object_names,
                )

            logger.info(
                "Deleted %d artifacts for audit_run %s",
                len(object_names),
                audit_run_id,
            )
            return len(object_names)

        except S3Error as e:
            raise RuntimeError(
                f"Failed to delete artifacts for audit_run {audit_run_id}: {e}"
            ) from e

    async def close(self) -> None:
        """Close the MinIO client (cleanup if needed)."""
        # minio.Minio doesn't require explicit cleanup, but we log for consistency
        logger.info("MinIOClient closed")

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _build_path(audit_run_id: UUID, artifact_name: str) -> str:
        """Build the full object path from audit_run_id and artifact_name."""
        return f"audits/{audit_run_id}/{artifact_name}"


# ---------------------------------------------------------------------------
# Module-level factory
# ---------------------------------------------------------------------------

_client: Optional[MinIOClient] = None


async def init_minio(
    endpoint: Optional[str] = None,
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    bucket: Optional[str] = None,
    secure: Optional[bool] = None,
) -> None:
    """
    Initialize the global MinIO client.

    If parameters are not provided, they are read from:
    - Environment variables (MINIO_ENDPOINT, MINIO_BUCKET, MINIO_SECURE)
    - Keyvault secrets (minio/user, minio/password)

    Args:
        endpoint: MinIO endpoint (default: from env)
        access_key: Access key (default: from keyvault)
        secret_key: Secret key (default: from keyvault)
        bucket: Bucket name (default: from env)
        secure: Use TLS (default: from env)

    Raises:
        RuntimeError: If credentials cannot be resolved or bucket creation fails
    """
    global _client

    # Resolve endpoint
    if endpoint is None:
        endpoint = MINIO_ENDPOINT

    # Resolve bucket
    if bucket is None:
        bucket = MINIO_BUCKET

    # Resolve secure flag
    if secure is None:
        secure = MINIO_SECURE

    # Resolve credentials from keyvault if not provided
    if access_key is None or secret_key is None:
        try:
            secrets = await get_secrets(
                ["minio/user", "minio/password"]
            )
            if access_key is None:
                access_key = secrets["minio/user"]
            if secret_key is None:
                secret_key = secrets["minio/password"]
        except KeyError as e:
            raise RuntimeError(
                f"MinIO credentials not found in keyvault: {e}. "
                f"Ensure 'minio/user' and 'minio/password' are set."
            ) from e

    # Initialize client
    _client = MinIOClient(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
        secure=secure,
    )

    # Verify bucket exists
    await _client.ensure_bucket()


async def get_minio_client() -> MinIOClient:
    """
    Get the global MinIO client.

    Raises:
        RuntimeError: If client has not been initialized
    """
    if _client is None:
        raise RuntimeError(
            "MinIO client not initialized. Call init_minio() first."
        )
    return _client


async def close_minio() -> None:
    """Close the global MinIO client."""
    global _client
    if _client:
        await _client.close()
        _client = None
        logger.info("MinIO client closed")
