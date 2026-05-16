"""
Unit tests for tron.infra.secrets.__init__ conditional imports.

Tests the VAULT_BACKEND configuration that selects between
KMac Vault and HashiCorp Vault clients.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


class TestVaultBackendSelection:
    """Test conditional import of vault client based on VAULT_BACKEND."""

    @pytest.fixture(autouse=True)
    def _preserve_secrets_modules(self):
        """Save and restore tron.infra.secrets* modules around each test."""
        saved = {
            k: v for k, v in sys.modules.items()
            if k.startswith("tron.infra.secrets")
        }
        yield
        # Restore originals
        for k in list(sys.modules):
            if k.startswith("tron.infra.secrets"):
                del sys.modules[k]
        sys.modules.update(saved)

    def test_kmac_backend_import(self):
        """When VAULT_BACKEND=kmac, should import KMacVaultClient."""
        if "tron.infra.secrets" in sys.modules:
            del sys.modules["tron.infra.secrets"]

        with patch.dict("os.environ", {"VAULT_BACKEND": "kmac"}):
            import tron.infra.secrets

            assert hasattr(tron.infra.secrets, "KeyvaultClient")
            assert tron.infra.secrets.KeyvaultClient.__name__ == "KMacVaultClient"

    def test_hashicorp_backend_import(self):
        """When VAULT_BACKEND=hashicorp, should import HashiCorp Vault client."""
        if "tron.infra.secrets" in sys.modules:
            del sys.modules["tron.infra.secrets"]

        with patch.dict("os.environ", {"VAULT_BACKEND": "hashicorp"}):
            import tron.infra.secrets

            assert hasattr(tron.infra.secrets, "KeyvaultClient")
            assert tron.infra.secrets.KeyvaultClient.__name__ == "KeyvaultClient"

    def test_default_backend_is_kmac(self):
        """Default VAULT_BACKEND should be kmac."""
        if "tron.infra.secrets" in sys.modules:
            del sys.modules["tron.infra.secrets"]

        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("VAULT_BACKEND", None)

            import tron.infra.secrets

            assert tron.infra.secrets.KeyvaultClient.__name__ == "KMacVaultClient"

    def test_module_exports(self):
        """Module should export KeyvaultClient, get_secret, and get_secrets."""
        if "tron.infra.secrets" in sys.modules:
            del sys.modules["tron.infra.secrets"]

        with patch.dict("os.environ", {"VAULT_BACKEND": "kmac"}):
            import tron.infra.secrets

            assert hasattr(tron.infra.secrets, "KeyvaultClient")
            assert hasattr(tron.infra.secrets, "get_secret")
            assert hasattr(tron.infra.secrets, "get_secrets")

            assert "KeyvaultClient" in tron.infra.secrets.__all__
            assert "get_secret" in tron.infra.secrets.__all__
            assert "get_secrets" in tron.infra.secrets.__all__
