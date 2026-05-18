# AWS KMS auto-unseal — operator runbook

> Applies to Spine v3 deployment shapes (#17): **BYOC on AWS**,
> **customer-cloud (EKS)**, **on-prem with hybrid AWS KMS access**.

## What KMS auto-unseal gives you

Vault stores its master key encrypted by an AWS KMS Customer Master Key (CMK).
On startup, Vault calls `kms:Decrypt` to recover the master key automatically.
No human intervention to unseal.

You still receive **recovery keys** (Shamir-split, default 3-of-5) at init.
These are NOT for daily unseal; they are the disaster fallback if the KMS key
becomes unavailable (account compromise, region outage, deletion).

## Pre-requisites

1. AWS account with permission to create KMS keys.
2. IAM role / user that the OpenBao container can assume (IRSA on EKS, EC2
   instance profile on EC2, or static creds via Spine vault — chicken-and-egg
   avoided because this is the FIRST vault).
3. KMS key region decided. Multi-region key strongly recommended for DR.

## Step 1 — create KMS key

```bash
aws kms create-key \
  --description "Spine OpenBao auto-unseal" \
  --key-usage ENCRYPT_DECRYPT \
  --key-spec SYMMETRIC_DEFAULT \
  --multi-region \
  --tags TagKey=app,TagValue=spine TagKey=purpose,TagValue=vault-unseal

# Note the KeyId. Create a friendly alias:
aws kms create-alias --alias-name alias/spine-vault-unseal \
  --target-key-id <KeyId>
```

## Step 2 — IAM policy for the OpenBao container

Minimum required actions on the KMS key:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "VaultAutoUnseal",
      "Effect": "Allow",
      "Action": [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:DescribeKey"
      ],
      "Resource": "arn:aws:kms:<region>:<account>:key/<KeyId>"
    }
  ]
}
```

Attach to the role/profile the container uses.

## Step 3 — Vault server HCL (BEFORE first init)

The seal stanza MUST be present before `init-wizard.sh` runs. Override the
default `BAO_LOCAL_CONFIG` in `docker-compose.yml` (or your k8s ConfigMap):

```hcl
ui = true
disable_mlock = false

storage "raft" {
  path    = "/openbao/data"
  node_id = "spine-vault-aws-1"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_cert_file = "/openbao/tls/cert.pem"
  tls_key_file  = "/openbao/tls/key.pem"
}

seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "alias/spine-vault-unseal"
  # No access_key / secret_key — rely on instance profile / IRSA.
}

api_addr     = "https://vault.your-spine.example:8200"
cluster_addr = "https://vault.your-spine.example:8201"
```

Start the container. Vault will detect "uninitialized + seal configured" and
wait for `init-wizard.sh`.

## Step 4 — run the wizard

```bash
./vault/init-wizard.sh --unseal=aws --recovery-output=/secure/aws-init.json
```

The wizard issues **recovery shares** (not unseal shares). KMS handles unseal
on every restart automatically.

## Step 5 — verify auto-unseal

```bash
docker compose -f vault/docker-compose.yml restart vault
sleep 5
curl -s http://127.0.0.1:8200/v1/sys/seal-status | jq .sealed
# Expect: false
```

## DR scenarios

| Failure | Recovery |
|---|---|
| AWS region down | If multi-region KMS key + cross-region replica configured, fail over. Otherwise wait. |
| KMS key scheduled for deletion | Cancel deletion before 7d grace period expires. KMS deletion is the most common cause of "auto-unseal stopped working." |
| KMS key permanently deleted | Use recovery shares to migrate to a new seal: `bao operator seal-migrate`. |
| IAM permissions revoked | Restore the IAM grant; restart container. |
| AWS account locked out | Use recovery shares offline + new AWS account / different cloud. See `../dr-runbook.md` "KMS loss" path. |

## Key rotation

KMS keys rotate yearly by default. Vault tracks the active version
automatically; no action needed unless you rotate manually:

```bash
aws kms enable-key-rotation --key-id alias/spine-vault-unseal
```

## References

- OpenBao AWS KMS seal: <https://openbao.org/docs/configuration/seal/awskms/>
- AWS KMS multi-region: <https://docs.aws.amazon.com/kms/latest/developerguide/multi-region-keys-overview.html>
- Spine DR runbook: `../dr-runbook.md`
