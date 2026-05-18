# Azure Key Vault auto-unseal — operator runbook

> Applies to Spine v3 deployment shapes (#17): **BYOC on Azure**,
> **customer-cloud (AKS)**, **on-prem with hybrid Azure access**.

## What this gives you

Vault stores its master key wrapped by an Azure Key Vault key. On startup,
Vault calls `keys/unwrapKey` to recover automatically. Recovery shares
(Shamir-split, default 3-of-5) are issued at init for the catastrophic-loss
path.

## Pre-requisites

1. Azure subscription + resource group.
2. Azure Key Vault instance (HSM-backed Premium SKU recommended for production).
3. Service Principal OR Managed Identity that the OpenBao container can use
   (Managed Identity strongly preferred on AKS via Workload Identity).

## Step 1 — create the Key Vault + wrapping key

```bash
RG=spine-prod
LOC=eastus
KV_NAME=spine-vault-unseal-kv

az keyvault create -n $KV_NAME -g $RG -l $LOC \
  --sku premium --enable-purge-protection true \
  --retention-days 90

az keyvault key create --vault-name $KV_NAME -n spine-vault-unseal-key \
  --kty RSA-HSM --size 2048 --ops wrapKey unwrapKey
```

**Purge protection is REQUIRED.** Without it, a deleted key can be permanently
purged in 7 days, killing your ability to unseal.

## Step 2 — grant the container identity access

For Managed Identity (`<principal-id>` = the AKS pod's identity):

```bash
az keyvault set-policy -n $KV_NAME --object-id <principal-id> \
  --key-permissions get wrapKey unwrapKey
```

For Service Principal: same command, `--spn <appid>`.

## Step 3 — Vault server HCL (BEFORE first init)

```hcl
ui = true
disable_mlock = false

storage "raft" {
  path    = "/openbao/data"
  node_id = "spine-vault-azure-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/openbao/tls/cert.pem"
  tls_key_file  = "/openbao/tls/key.pem"
}

seal "azurekeyvault" {
  tenant_id  = "<tenant-id>"
  vault_name = "spine-vault-unseal-kv"
  key_name   = "spine-vault-unseal-key"
  # client_id / client_secret omitted — Managed Identity preferred.
  # For SP auth, inject via Spine vault NOT env file.
}

api_addr     = "https://vault.your-spine.example:8200"
cluster_addr = "https://vault.your-spine.example:8201"
```

## Step 4 — run the wizard

```bash
./vault/init-wizard.sh --unseal=azure --recovery-output=/secure/azure-init.json
```

## Step 5 — verify

```bash
curl -s http://127.0.0.1:8200/v1/sys/seal-status | jq .sealed
# Expect: false
```

## DR scenarios

| Failure | Recovery |
|---|---|
| Key Vault region down | If geo-replicated Key Vault, failover. Otherwise wait. |
| Key soft-deleted | Recover within 90d retention: `az keyvault key recover`. |
| Key purged | Use recovery shares to seal-migrate to a new key. |
| Managed Identity revoked | Restore identity grant; restart container. |
| Tenant locked out | Recovery shares + new tenant / different cloud. |

## Key rotation

Azure Key Vault supports automatic rotation on RSA-HSM keys:

```bash
az keyvault key rotation-policy update --vault-name $KV_NAME \
  --name spine-vault-unseal-key \
  --value @rotation-policy.json
```

Vault re-wraps the master key transparently.

## References

- OpenBao Azure Key Vault seal: <https://openbao.org/docs/configuration/seal/azurekeyvault/>
- Azure Key Vault soft-delete: <https://learn.microsoft.com/azure/key-vault/general/soft-delete-overview>
- Spine DR runbook: `../dr-runbook.md`
