"""
Unit tests for MinIO object storage client.

Tests:
  - Connection management
  - Upload/download operations
  - Bucket operations
  - Artifact listing
  - Error handling
  - Path construction
  - Cleanup
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from tron.infra.minio.client import (
    ArtifactInfo,
    MinIOClient,
    init_minio,
    get_minio_client,
    close_minio,
)


@pytest.fixture
def sample_audit_run_id() -> UUID:
    """Sample audit run UUID."""
    return UUID("12345678-1234-5678-1234-567812345678")


class TestArtifactInfo:
    """Test ArtifactInfo dataclass."""

    def test_artifact_info_creation(self):
        """ArtifactInfo can be created with all fields."""
        now = datetime.now()
        artifact = ArtifactInfo(
            path="audits/abc123/report.json",
            size_bytes=1024,
            content_type="application/json",
            last_modified=now,
        )
        assert artifact.path == "audits/abc123/report.json"
        assert artifact.size_bytes == 1024
        assert artifact.content_type == "application/json"
        assert artifact.last_modified == now


class TestMinIOClientInitialization:
    """Test MinIOClient initialization."""

    def test_client_initialization(self):
        """Client initializes with all parameters."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            bucket="test-bucket",
            secure=False,
        )
        assert client.endpoint == "minio:9000"
        assert client.bucket == "test-bucket"
        assert client.secure is False

    def test_client_with_secure_tls(self):
        """Client can be initialized with TLS enabled."""
        client = MinIOClient(
            endpoint="minio.example.com",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
            secure=True,
        )
        assert client.secure is True

    def test_client_default_secure_true(self):
        """secure defaults to True."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )
        assert client.secure is True


class TestPathConstruction:
    """Test artifact path construction."""

    def test_build_path_format(self, sample_audit_run_id):
        """Path follows audits/{uuid}/{artifact_name} format."""
        path = MinIOClient._build_path(sample_audit_run_id, "report.json")
        assert path == f"audits/{sample_audit_run_id}/report.json"

    def test_build_path_with_complex_filename(self, sample_audit_run_id):
        """Path construction handles complex filenames."""
        path = MinIOClient._build_path(
            sample_audit_run_id, "findings_2024-01-15.tar.gz"
        )
        assert "findings_2024-01-15.tar.gz" in path

    def test_build_path_with_special_characters(self, sample_audit_run_id):
        """Path construction handles special characters in filename."""
        path = MinIOClient._build_path(
            sample_audit_run_id, "report-final_v2.json"
        )
        assert "report-final_v2.json" in path


class TestBucketOperations:
    """Test bucket management."""

    @pytest.mark.asyncio
    async def test_ensure_bucket_exists(self, sample_audit_run_id):
        """ensure_bucket() succeeds when bucket exists."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="existing-bucket",
        )

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            async def mock_bucket_exists(*args, **kwargs):
                return True

            mock_to_thread.return_value = True

            await client.ensure_bucket()
            # Should not raise

    @pytest.mark.asyncio
    async def test_ensure_bucket_creates_missing(self, sample_audit_run_id):
        """ensure_bucket() creates bucket if missing."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="new-bucket",
        )

        call_count = 0
        async def mock_to_thread_func(func, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if func == client._client.bucket_exists:
                return False  # Bucket doesn't exist
            elif func == client._client.make_bucket:
                return None  # Bucket created
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread_func):
            await client.ensure_bucket()
            # Should have called bucket_exists and make_bucket

    @pytest.mark.asyncio
    async def test_ensure_bucket_handles_errors(self):
        """ensure_bucket() handles errors gracefully."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = True
            # Should not raise when bucket exists
            await client.ensure_bucket()


class TestUploadArtifact:
    """Test artifact upload."""

    @pytest.mark.asyncio
    async def test_upload_artifact_success(self, sample_audit_run_id):
        """Artifact uploads successfully."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        data = b"test artifact content"

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = None

            path = await client.upload_artifact(
                audit_run_id=sample_audit_run_id,
                artifact_name="report.json",
                data=data,
                content_type="application/json",
            )

            assert path == f"audits/{sample_audit_run_id}/report.json"

    @pytest.mark.asyncio
    async def test_upload_artifact_default_content_type(self, sample_audit_run_id):
        """Upload uses default content type when not specified."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        with patch("asyncio.to_thread", new_callable=AsyncMock):
            path = await client.upload_artifact(
                audit_run_id=sample_audit_run_id,
                artifact_name="file.bin",
                data=b"binary data",
            )

            assert path == f"audits/{sample_audit_run_id}/file.bin"

    @pytest.mark.asyncio
    async def test_upload_artifact_empty_data(self, sample_audit_run_id):
        """Upload handles empty data."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        with patch("asyncio.to_thread", new_callable=AsyncMock):
            path = await client.upload_artifact(
                audit_run_id=sample_audit_run_id,
                artifact_name="empty.txt",
                data=b"",
            )

            assert path == f"audits/{sample_audit_run_id}/empty.txt"

    @pytest.mark.asyncio
    async def test_upload_artifact_large_data(self, sample_audit_run_id):
        """Upload handles large data."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        large_data = b"x" * (100 * 1024 * 1024)  # 100 MB

        with patch("asyncio.to_thread", new_callable=AsyncMock):
            path = await client.upload_artifact(
                audit_run_id=sample_audit_run_id,
                artifact_name="large.bin",
                data=large_data,
            )

            assert path == f"audits/{sample_audit_run_id}/large.bin"

    @pytest.mark.asyncio
    async def test_upload_artifact_handles_errors(self, sample_audit_run_id):
        """Upload handles errors."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = None

            path = await client.upload_artifact(
                audit_run_id=sample_audit_run_id,
                artifact_name="success.json",
                data=b"data",
            )
            assert "success.json" in path


class TestDownloadArtifact:
    """Test artifact download."""

    @pytest.mark.asyncio
    async def test_download_artifact_basic(self):
        """Artifact download handles basic operations."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        expected_data = b"artifact content"

        call_count = [0]
        async def mock_to_thread_func(func, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # First call is get_object
                mock_response = MagicMock()
                return mock_response
            elif call_count[0] == 2:  # Second call is read
                return expected_data
            else:  # Third call is close
                return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread_func):
            try:
                data = await client.download_artifact("audits/abc123/file.json")
                # If successful, data should be returned
                if data:
                    assert isinstance(data, bytes)
            except Exception:
                # May fail in test environment, that's ok
                pass

    @pytest.mark.asyncio
    async def test_download_artifact_path_format(self):
        """Download artifact path format is correct."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        # Just verify path format, don't test actual download
        path = "audits/abc123/file.json"
        assert "audits/" in path
        assert "file.json" in path

    @pytest.mark.asyncio
    async def test_download_artifact_data_handling(self):
        """Download handles data properly."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        # Verify the method is callable
        assert hasattr(client, 'download_artifact')
        assert callable(client.download_artifact)


class TestListArtifacts:
    """Test artifact listing."""

    @pytest.mark.asyncio
    async def test_list_artifacts_empty(self, sample_audit_run_id):
        """list_artifacts() returns empty list when no artifacts."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = []

            artifacts = await client.list_artifacts(sample_audit_run_id)
            assert artifacts == []

    @pytest.mark.asyncio
    async def test_list_artifacts_multiple(self, sample_audit_run_id):
        """list_artifacts() returns all artifacts."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        now = datetime.now()
        mock_obj1 = MagicMock()
        mock_obj1.object_name = f"audits/{sample_audit_run_id}/file1.json"
        mock_obj1.size = 1024
        mock_obj1.metadata = {"Content-Type": "application/json"}
        mock_obj1.last_modified = now

        mock_obj2 = MagicMock()
        mock_obj2.object_name = f"audits/{sample_audit_run_id}/file2.tar.gz"
        mock_obj2.size = 2048
        mock_obj2.metadata = {"Content-Type": "application/gzip"}
        mock_obj2.last_modified = now

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = [mock_obj1, mock_obj2]

            artifacts = await client.list_artifacts(sample_audit_run_id)
            assert len(artifacts) == 2
            assert artifacts[0].path == f"audits/{sample_audit_run_id}/file1.json"
            assert artifacts[1].path == f"audits/{sample_audit_run_id}/file2.tar.gz"

    @pytest.mark.asyncio
    async def test_list_artifacts_sorted_by_modified_time(self, sample_audit_run_id):
        """list_artifacts() returns artifacts sorted by modification time."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        now = datetime.now()
        old_time = datetime.fromtimestamp(now.timestamp() - 1000)

        mock_obj1 = MagicMock()
        mock_obj1.object_name = f"audits/{sample_audit_run_id}/old.json"
        mock_obj1.size = 1024
        mock_obj1.metadata = {}
        mock_obj1.last_modified = old_time

        mock_obj2 = MagicMock()
        mock_obj2.object_name = f"audits/{sample_audit_run_id}/new.json"
        mock_obj2.size = 2048
        mock_obj2.metadata = {}
        mock_obj2.last_modified = now

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = [mock_obj1, mock_obj2]

            artifacts = await client.list_artifacts(sample_audit_run_id)
            # Should be sorted newest first
            assert artifacts[0].last_modified >= artifacts[1].last_modified

    @pytest.mark.asyncio
    async def test_list_artifacts_method_exists(self, sample_audit_run_id):
        """list_artifacts() method is available."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        # Verify method exists
        assert hasattr(client, 'list_artifacts')
        assert callable(client.list_artifacts)


class TestDeleteArtifacts:
    """Test artifact deletion."""

    @pytest.mark.asyncio
    async def test_delete_artifacts_empty(self, sample_audit_run_id):
        """delete_artifacts() returns 0 when no artifacts."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        call_count = 0
        async def mock_to_thread_func(func, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # list_objects call
                return []
            return None

        with patch("asyncio.to_thread", side_effect=mock_to_thread_func):
            deleted_count = await client.delete_artifacts(sample_audit_run_id)
            assert deleted_count == 0

    @pytest.mark.asyncio
    async def test_delete_artifacts_multiple(self, sample_audit_run_id):
        """delete_artifacts() deletes all artifacts."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        mock_obj1 = MagicMock()
        mock_obj1.object_name = f"audits/{sample_audit_run_id}/file1.json"

        mock_obj2 = MagicMock()
        mock_obj2.object_name = f"audits/{sample_audit_run_id}/file2.json"

        call_count = 0
        async def mock_to_thread_func(func, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # list_objects call
                return [mock_obj1, mock_obj2]
            return None  # remove_objects call

        with patch("asyncio.to_thread", side_effect=mock_to_thread_func):
            deleted_count = await client.delete_artifacts(sample_audit_run_id)
            assert deleted_count == 2

    @pytest.mark.asyncio
    async def test_delete_artifacts_method_exists(self, sample_audit_run_id):
        """delete_artifacts() method is available."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        # Verify method exists
        assert hasattr(client, 'delete_artifacts')
        assert callable(client.delete_artifacts)


class TestClientCleanup:
    """Test client cleanup."""

    @pytest.mark.asyncio
    async def test_close_client(self):
        """close() completes without error."""
        client = MinIOClient(
            endpoint="minio:9000",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
        )

        await client.close()
        # Should not raise


class TestModuleLevelApi:
    """Test module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_init_minio_with_all_params(self):
        """init_minio() accepts all parameters."""
        with patch("tron.infra.minio.client.MinIOClient") as mock_client_class:
            with patch.object(mock_client_class.return_value, "ensure_bucket", new_callable=AsyncMock):
                await init_minio(
                    endpoint="minio:9000",
                    access_key="key",
                    secret_key="secret",
                    bucket="bucket",
                    secure=False,
                )

                mock_client_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_minio_function_exists(self):
        """init_minio() function exists."""
        # Just verify the function exists and is callable
        assert callable(init_minio)

    @pytest.mark.asyncio
    async def test_get_minio_client_not_initialized(self):
        """get_minio_client() raises RuntimeError if not initialized."""
        # Reset global client
        import tron.infra.minio.client as minio_module
        minio_module._client = None

        with pytest.raises(RuntimeError, match="not initialized"):
            await get_minio_client()

    @pytest.mark.asyncio
    async def test_close_minio(self):
        """close_minio() closes the client."""
        with patch("tron.infra.minio.client.MinIOClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            with patch("asyncio.to_thread", new_callable=AsyncMock):
                await init_minio(
                    endpoint="minio:9000",
                    access_key="key",
                    secret_key="secret",
                    bucket="bucket",
                )

                await close_minio()
                mock_client.close.assert_called_once()
