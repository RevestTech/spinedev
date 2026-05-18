# GCP KMS auto-unseal — operator runbook

> Applies to Spine v3 deployment shapes (#17): **BYOC on GCP**,
> **customer-cloud (GKE)**, **on-prem with hybrid GCP access**.

## What this gives you

Vault stores its master key wrapped by a Cloud KMS key. On startup, Vault
calls `cryptoKeyVersions.decrypt` to recover automatically. Recovery shares
(Shamir-split, default 3-of-5) are issued at init for the catastrophic-loss
path.

## Pre-requisites

1. GCP project + billing.
2. Cloud KMS API enabled (`cloudkms.googleapis.com`).
3. Service Account that the OpenBao container can use (Workload Identity on
   GKE strongly preferred; SA JSON keys discouraged).

## Step 1 — create keyring + key

```bash
PROJECT=spine-prod
LOC=global
KR=spine-vault-unseal
KEY=spine-vault-unseal-key

gcloud kms keyrings create $KR --location=$LOC --project=$PROJECT

gcloud kms keys create $KEY \
  --keyring=$KR --location=$LOC --project=$PROJECT \
  --purpose=encryption \
  --rotation-period=90d \
  --next-rotation-time="$(date -u -d '+90 days' --iso-8601=seconds)"
```

## Step 2 — grant the container's Service Account

```bash
SA=spine-vault@$PROJECT.iam.gserviceaccount.com

gcloud kms keys add-iam-policy-binding $KEY \
  --keyring=$KR --location=$LOC --project=$PROJECT \
  --member=serviceAccount:$SA \
  --role=roles/cloudkms.cryptoKeyEncrypterDecrypter
```

For GKE Workload Identity, bind the K8s service account to the GCP SA:

```bash
gcloud iam service-accounts add-iam-policy-binding $SA \
  --role=roles/iam.workloadIdentityUser \
  --member="serviceAccount:$PROJECT.svc.id.goog[spine/vault]"
```

## Step 3 — Vault server HCL (BEFORE first init)

```hcl
ui = true
disable_mlock = false

storage "raft" {
  path    = "/openbao/data"
  node_id = "spine-vault-gcp-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/openbao/tls/cert.pem"
  tls_key_file  = "/openbao/tls/key.pem"
}

seal "gcpckms" {
  project     = "spine-prod"
  region      = "global"
  key_ring    = "spine-vault-unseal"
  crypto_key  = "spine-vault-unseal-key"
  # credentials field omitted — Workload Identity / ADC preferred.
}

api_addr     = "https://vault.your-spine.example:8200"
cluster_addr = "https://vault.your-spine.example:8201"
```

## Step 4 — run the wizard

```bash
./vault/init-wizard.sh --unseal=gcp --recovery-output=/secure/gcp-init.json
```

## Step 5 — verify

```bash
curl -s http://127.0.0.1:8200/v1/sys/seal-status | jq .sealed
# Expect: false
```

## DR scenarios

| Failure | Recovery |
|---|---|
| Region outage (regional keyring) | Use a `global` keyring (as configured above) or replicate to a second region. |
| Key version destroyed | KMS retains destroyed key versions for 24h. Restore before window expires: `gcloud kms keys versions restore`. |
| Permanently destroyed | Use recovery shares to seal-migrate to a new key. |
| Workload Identity broken | Re-bind KSA↔GSA; restart container. |
| Project deleted | 30d grace period; restore project, then keys auto-restore. After grace: recovery shares + new project. |

## Key rotation

`--rotation-period=90d` set above triggers automatic rotation. Vault
re-wraps on next rotation. No action needed.

## References

- OpenBao GCP CKMS seal: <https://openbao.org/docs/configuration/seal/gcpckms/>
- GKE Workload Identity: <https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity>
- Spine DR runbook: `../dr-runbook.md`
