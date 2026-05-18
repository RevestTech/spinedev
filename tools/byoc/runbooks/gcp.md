# GCP BYOC Runbook

> Operator-facing playbook for provisioning a Spine Hub into a **customer's GCP project** via vendor service-account delegation. Pair with [`tools/byoc/clouds/gcp.sh`](../clouds/gcp.sh). Drivers: `docs/V3_DESIGN_DECISIONS.md` §15, §17, §20.

---

## 1. What this provisions

| Component | GCP resource | Mode `gce` (default) | Mode `gke` |
|---|---|---|---|
| Network | Custom VPC + subnet (10.42.0.0/20) + firewall rules | ✔ | ✔ |
| Compute | Hub + Vault + Keycloak | e2-medium GCE VM (Container-Optimized OS) | GKE Autopilot (Workload Identity ON) |
| Postgres | Cloud SQL db-f1-micro, private IP, automated backups | ✔ | ✔ |
| Secrets | Secret Manager — 5 EMPTY slots seeded | ✔ | ✔ |
| Identity binding | service account `spine-hub-vm@…` (GCE) / Workload Identity binding (GKE) | ✔ | ✔ |
| TLS | Reserved external IP + managed cert (GCLB) | ✔ | ✔ |

All labels: `spine-byoc=true,spine-hub-version=<v>,managed-by=spine-vendor`.

## 2. What the customer must grant Spine

A vendor-controlled **service account** with scoped IAM bindings on **one project only**.

```bash
# Customer runs in their project:
gcloud projects add-iam-policy-binding <customer-project> \
    --member="serviceAccount:spine-ops@<vendor-project>.iam.gserviceaccount.com" \
    --role="roles/owner"   # narrow further with custom role; see below
```

Narrower role set (recommended):

- `roles/compute.networkAdmin` + `roles/compute.instanceAdmin.v1`
- `roles/container.admin` (GKE mode)
- `roles/cloudsql.admin`
- `roles/secretmanager.admin`
- `roles/iam.serviceAccountAdmin` + `roles/iam.serviceAccountUser`
- `roles/dns.admin` (only if vendor manages the customer's hosted zone)
- `roles/logging.viewer` + `roles/monitoring.viewer` (for ops visibility)

## 3. Provisioning

```bash
# 1. Vendor stores the SA key in vault.
spine-vault kv put kv/byoc/<customer-project>/gcp_sa @path/to/spine-ops-key.json

# 2. Dry-run.
tools/byoc/provision.sh --non-interactive --dry-run \
    --cloud=gcp --account=<customer-project> \
    --region=us-central1 --mode=gce \
    --hub-version=1.0.0 --bundle-id=$(uuidgen) \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/<customer-project>/gcp_sa

# 3. Real run (drop --dry-run).
```

## 4. Success criteria

- `gcloud compute instances list --filter='labels.spine-byoc=true' --project <customer-project>` shows `spine-hub-vm` running
- `gcloud secrets list --filter='labels.spine-byoc=true' --project <customer-project>` shows the 5 slots
- Hub serves `/healthz` on the reserved IP
- (GKE) `kubectl get pods -n spine` shows Hub pod with Workload Identity service account

## 5. Rollback / teardown

```bash
tools/byoc/provision.sh --destroy --cloud=gcp \
    --account=<customer-project> \
    --credentials-ref=vault://kv/byoc/<customer-project>/gcp_sa --force
```

Order: GKE/GCE compute → Cloud SQL → Secret Manager slots → firewall → VPC. Cloud SQL deletion does NOT delete automated backups unless `--backup-retention=0` is explicitly set; default runbook keeps them for restore-on-disaster.

## 6. Exit ramp

1. Customer removes IAM binding for vendor service account on their project.
2. Hub keeps running on customer-owned infra. Customer rotates Keycloak admin via Secret Manager.
3. (Optional) `spine export | spine import` into a customer-controlled GKE cluster for full self-hosted ownership.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `gcloud projects describe` returns PERMISSION_DENIED | IAM binding not yet propagated | wait 5 min; re-run |
| Cloud SQL stuck in `PENDING_CREATE` for >15 min | private services access not configured | `gcloud compute addresses create google-managed-services-spine-hub-vpc --global --purpose=VPC_PEERING --network=spine-hub-vpc --prefix-length=16` then `gcloud services vpc-peerings connect …` |
| Workload Identity pod cannot read Secret Manager | k8s SA → IAM SA binding missing | re-run the `iam.workloadIdentityUser` binding step in `clouds/gcp.sh` |
| Managed cert stuck in `PROVISIONING` | DNS A record for hostname doesn't yet resolve to reserved IP | confirm DNS first; the managed cert provisioner retries automatically |
| `--destroy` says "subnet in use" | GKE managed firewall rules linger | `gcloud compute firewall-rules list --filter='network=spine-hub-vpc'` → delete leftovers |

## 8. Cost guardrails

GCE mode minimum monthly (us-central1):

- e2-medium GCE: ~$25
- Cloud SQL db-f1-micro: ~$10
- GCLB + reserved IP: ~$25
- Secret Manager: ~$1
- **Total: ~$60/mo + egress**

GKE Autopilot mode: ~$73/mo control-plane + per-pod resource billing (Autopilot bills only for requested CPU/memory). Typically ~$110/mo all-in. Recommend `gce` for Founder tier.

## 9. References

- [`tools/byoc/provision.sh`](../provision.sh)
- [`tools/byoc/clouds/gcp.sh`](../clouds/gcp.sh)
- [`docs/DEPLOYMENT_SHAPES.md`](../../../docs/DEPLOYMENT_SHAPES.md)
- GCP Workload Identity: <https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity>
