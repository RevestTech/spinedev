# 🔐 Tron Vault Migration — Action Required

## What Happened

Your secrets have been **migrated from tron-vault to KMac Vault** (central vault).

**Old vault**: `tron-vault` on port 13001 (REMOVED ✅)  
**New vault**: `kmac-vault` on port 9999 (ACTIVE ✅)

---

## Your Secrets

All 7 secrets have been migrated with the `tron:` prefix:

```
✅ tron:auth_jwt_secret
✅ tron:auth_master_key  
✅ tron:auth_secret_key
✅ tron:db_password
✅ tron:llm_anthropic_key  (REAL API key)
✅ tron:llm_openai_key     (REAL API key)
✅ tron:redis_password
```

---

## Quick Test

Verify your secrets are accessible:

```bash
# Using kmac CLI (easiest)
kmac vault get tron:db_password

# Using curl directly
TOKEN=$(cat ~/.config/kmac/docker-vault-token)
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:9999/get/tron:db_password
```

---

## Update Your Code

### Option 1: Use KMac Vault Client (Recommended)

Install the kmac-vault Python client:

```python
import requests

VAULT_URL = "http://host.docker.internal:9999"  # From Docker container
# VAULT_URL = "http://127.0.0.1:9999"  # From host machine

with open("/vault-token") as f:  # Mount token in container
    TOKEN = f.read().strip()

def get_secret(key: str) -> str:
    """Get secret from kmac-vault."""
    response = requests.get(
        f"{VAULT_URL}/get/{key}",
        headers={"Authorization": f"Bearer {TOKEN}"}
    )
    response.raise_for_status()
    return response.json()["value"]

# Usage
db_password = get_secret("tron:db_password")
jwt_secret = get_secret("tron:auth_jwt_secret")
```

### Option 2: Update docker-compose.yml

Update your Tron services to use kmac-vault:

```yaml
services:
  tron-api:
    environment:
      # Remove old vault config
      # VAULT_ADDR: http://vault:8200
      # VAULT_TOKEN: tron-dev-token
      
      # Add kmac-vault config
      KMAC_VAULT_URL: http://host.docker.internal:9999
      KMAC_VAULT_PREFIX: "tron:"
    
    volumes:
      # Mount kmac-vault token
      - ~/.config/kmac/docker-vault-token:/vault-token:ro

# Remove old vault service
# vault:
#   image: hashicorp/vault:1.15.4
#   ...
```

---

## KMac Vault API Reference

**Base URL**: `http://127.0.0.1:9999` (host) or `http://host.docker.internal:9999` (Docker)  
**Auth**: Bearer token from `~/.config/kmac/docker-vault-token`

### Get Secret
```bash
GET /get/{key}
Authorization: Bearer {token}

Response: {"value": "secret-value"}
```

### Set Secret
```bash
POST /set
Authorization: Bearer {token}
Content-Type: application/json

Body: {"key": "project:name", "value": "secret"}
```

### List Keys
```bash
GET /list
Authorization: Bearer {token}

Response: ["key1", "key2", ...]
```

---

## Using KMac CLI

The easiest way to manage your secrets:

```bash
# Interactive vault browser
kmac vault

# List your secrets
kmac vault list | grep tron

# Get a secret value
kmac vault get tron:db_password

# Add/update secrets (wizard)
kmac vault set

# Project-specific manager
kmac vault project tron
```

---

## Migration Complete ✅

Your secrets are now in the central kmac-vault. The old tron-vault has been removed.

**Need help?** See full documentation: `/Users/khashsarrafi/Projects/KMac-CLI/VAULT_MIGRATION_NOTICE.md`
