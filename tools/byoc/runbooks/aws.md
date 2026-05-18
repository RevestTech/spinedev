# AWS BYOC Runbook

> Operator-facing playbook for provisioning a Spine Hub into a **customer's AWS account** via vendor-delegated role. Pair with [`tools/byoc/clouds/aws.sh`](../clouds/aws.sh). Drivers: `docs/V3_DESIGN_DECISIONS.md` §15 (NOT SaaS), §17 (BYOC), §20 (clouds).

---

## 1. What this provisions

A Founder-tier Spine Hub running inside the **customer's AWS account**:

| Component | AWS resource | Mode `ec2` | Mode `eks` |
|---|---|---|---|
| Network | VPC 10.42.0.0/16 + 2 subnets (multi-AZ) + IGW + RT + SGs | ✔ | ✔ |
| Compute | Hub + Vault + Keycloak + Postgres | 1× `t3.medium` EC2 (docker-compose) | 1×`t3.medium` EKS 1.28 node (helm) |
| Postgres | Internal-only (no public IP) | RDS db.t3.micro w/ managed-master-password | same |
| Secrets | Hub vault adapter = `aws` (Secrets Manager) | 5 EMPTY slots seeded | same |
| TLS | ACM cert (DNS-validated) | ALB HTTPS listener | same |
| DNS | Route 53 CNAME → ALB | ✔ | ✔ |

Everything is tagged `SpineBYOC=true,SpineHubVersion=<v>,SpineBundleId=<uuid>,ManagedBy=spine-vendor` so cost attribution + cleanup are mechanical.

## 2. What the customer must grant Spine

A **cross-account IAM role** named `SpineByocVendor` (or similar) in their account that the vendor's principal can `sts:AssumeRole` into.

### Trust policy (paste into the customer's IAM console)

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::<vendor-aws-account-id>:role/SpineByocAutomation" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "<unique-per-customer-id>" } }
  }]
}
```

### Permissions policy

Scope the role to the AWS services the script touches. **Do not** grant `*` — the runbook below assumes the operator narrowed permissions per the AWS docs:

- `ec2:*` on resources tagged `SpineBYOC=true`
- `rds:*` on `spine-hub-pg-*`
- `eks:*` on `spine-hub` cluster (EKS mode only)
- `elasticloadbalancing:*` on `spine-hub-alb`
- `acm:*Certificate*` on the issued cert
- `secretsmanager:*` on `spine/hub/*`
- `route53:ChangeResourceRecordSets` on the customer's hosted zone
- `iam:PassRole` for `SpineHubInstanceProfile` (EC2) or `SpineEKSClusterRole/NodeRole` (EKS)
- `sts:GetCallerIdentity` (always)

Use `Condition: StringEquals: aws:RequestTag/SpineBYOC=true` to scope create-style actions.

## 3. Provisioning

```bash
# 1. Store the delegated-role assume creds in the vendor vault.
#    (Vendor side; never on disk outside vault.)
spine-vault kv put kv/byoc/<account>/aws_assume_role \
    role_arn=arn:aws:iam::<customer-acct>:role/SpineByocVendor \
    external_id=<unique-per-customer-id>

# 2. Dry-run the full plan first.
tools/byoc/provision.sh --non-interactive --dry-run \
    --cloud=aws --account=arn:aws:iam::<customer-acct>:role/SpineByocVendor \
    --region=us-east-1 --mode=ec2 \
    --hub-version=1.0.0 --bundle-id=$(uuidgen) \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/<account>/aws_assume_role

# 3. Real run (drop --dry-run).
tools/byoc/provision.sh --non-interactive \
    --cloud=aws --account=arn:aws:iam::<customer-acct>:role/SpineByocVendor \
    --region=us-east-1 --mode=ec2 \
    --hub-version=1.0.0 --bundle-id=$(cat /tmp/bundle_id) \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/<account>/aws_assume_role
```

The orchestrator (a) validates the role assumes, (b) acquires a `.spine/byoc/aws.<account>.lock` file so two operators cannot race the same account, (c) dispatches to `clouds/aws.sh`. On success it prints a handoff banner with the Hub URL, admin email, and the location of the vault unseal shares (Secrets Manager slot `spine/hub/vault_unseal_shares`).

## 4. Success criteria

- `curl -fsS https://spine-hub.<customer-domain>/healthz` returns 200
- Hub login page loads, OIDC redirect to Keycloak works
- Customer can run `aws secretsmanager get-secret-value --secret-id spine/hub/vault_unseal_shares --version-stage AWSCURRENT --query SecretString --output text` to retrieve the 5 Shamir shards **once** (then rotate)
- `spine_federation.hub` row exists with `hub_id` matching the wizard manifest
- Workspace hygiene baseline (per #34) reports zero open workspaces on the Hub

## 5. Rollback / teardown

```bash
tools/byoc/provision.sh --destroy --cloud=aws \
    --account=arn:aws:iam::<customer-acct>:role/SpineByocVendor \
    --credentials-ref=vault://kv/byoc/<account>/aws_assume_role \
    --force
```

Order (script handles this):
1. Route 53 CNAME deleted
2. ALB + target-group + listener + ACM cert deleted
3. Secrets Manager slots deleted (force, no recovery window)
4. RDS instance deleted (skip final snapshot only if `--force` set — runbook default keeps snapshot)
5. EKS cluster + nodegroups deleted (EKS mode) OR EC2 instance terminated (EC2 mode)
6. Security groups, route tables, subnets, IGW, VPC deleted

Confirm with:

```bash
aws ec2 describe-vpcs --filters Name=tag:SpineBYOC,Values=true --region us-east-1
# → empty
```

## 6. Exit ramp (customer takes over)

This is the operational proof of "no lock-in" (#15). The customer:

1. Revokes the trust-policy entry on `SpineByocVendor` → vendor can no longer assume the role.
2. Hub keeps running. Customer assumes ops responsibility: rotate the Keycloak admin password, update DNS to a domain they own end-to-end, set their own backup target.
3. (Optional) migrate to Shape 3 self-hosted-customer-cloud per `docs/DEPLOYMENT_SHAPES.md`:

   ```bash
   spine export --output spine-state.tar.zst
   # Provision EKS yourself; helm install spine/hub; spine import …
   ```

   The deployment doesn't move; the data doesn't migrate; the audit chain stays continuous.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `delegated-role validation failed` | trust policy missing externalId, OR vendor principal renamed | re-issue trust policy block per §2 |
| `lock file exists` on re-run | crashed prior run | inspect `.spine/byoc/aws.<account>.lock`; re-run with `--force` after confirming no other operator is mid-flight |
| `RequestLimitExceeded` from EC2 mid-run | AWS API throttling under high tenant volume | re-run; orchestrator is idempotent (describe-then-create pattern) |
| ACM cert stuck in `PENDING_VALIDATION` | DNS validation record not yet added | `aws acm describe-certificate --certificate-arn <arn>` → copy `ValidationCNAME/Value` into customer's DNS |
| Hub `/healthz` 503 after provisioning | Postgres still warming up | wait 3–5 min; `kubectl logs -n spine deploy/spine-hub` (EKS) or `docker logs spine-hub` (EC2) for backoff messages |
| Vault unseal shares retrieved but Hub still sealed | Hub container restarted before unseal was POSTed | re-POST the shares via `https://spine-hub.<customer>/api/v1/vault/unseal` |

## 8. Cost guardrails

Single-EC2 mode minimum monthly steady-state (us-east-1):

- t3.medium EC2: ~$30
- RDS db.t3.micro: ~$15
- ALB: ~$22
- Route 53 hosted zone: ~$0.50
- ACM + Secrets Manager: ~$1
- **Total: ~$70/mo + data egress**

EKS mode adds ~$73/mo for the cluster control plane (EKS charge), so use `--mode=eks` only when the customer commits to ≥2 services or needs ingress patterns ALB can't do alone.

## 9. References

- [`tools/byoc/provision.sh`](../provision.sh) — orchestrator
- [`tools/byoc/clouds/aws.sh`](../clouds/aws.sh) — this cloud's implementation
- [`docs/V3_DESIGN_DECISIONS.md`](../../../docs/V3_DESIGN_DECISIONS.md) §15, §17, §20
- [`docs/DEPLOYMENT_SHAPES.md`](../../../docs/DEPLOYMENT_SHAPES.md) — per-shape × per-cloud capability matrix
- [`hub/wizard/init.sh`](../../../hub/wizard/init.sh) — Day-0 wizard the provisioner invokes
