# tron.infra.secrets — Keyvault integration for runtime secret retrieval
"""
Automatic vault client selection based on environment configuration.

Supports:
- KMac Vault: Set VAULT_BACKEND=kmac (recommended for production)
- HashiCorp Vault: Set VAULT_BACKEND=hashicorp (legacy)

Environment variables:
    VAULT_BACKEND: "kmac" or "hashicorp" (default: "kmac")
    
    For KMac Vault:
        KMAC_VAULT_URL: KMac vault URL (default: http://host.docker.internal:9999)
        KMAC_TOKEN_PATH: Token file path (default: /vault-token)
        KMAC_SECRET_PREFIX: Secret prefix (default: tron:)
    
    For HashiCorp Vault:
        VAULT_ADDR: Vault address (default: http://vault:8200)
        VAULT_TOKEN_PATH: Token file path (default: /run/secrets/vault-token)
        VAULT_SECRET_PREFIX: Secret prefix (default: tron)
"""

import os

VAULT_BACKEND = os.getenv("VAULT_BACKEND", "kmac").lower()

if VAULT_BACKEND == "kmac":
    from tron.infra.secrets.kmac_client import KMacVaultClient as KeyvaultClient
    from tron.infra.secrets.kmac_client import get_secret, get_secrets
else:
    from tron.infra.secrets.client import KeyvaultClient, get_secret, get_secrets

from tron.infra.secrets.llm_aliases import merge_anthropic_key_aliases

__all__ = ["KeyvaultClient", "get_secret", "get_secrets", "merge_anthropic_key_aliases"]
