# Azure BYOC Runbook

> Operator-facing playbook for provisioning a Spine Hub into a **customer's Azure subscription** via vendor-delegated access. Pair with [`tools/byoc/clouds/azure.sh`](../clouds/azure.sh). Drivers: `docs/V3_DESIGN_DECISIONS.md` §15, §17, §20.

---

## 1. What this provisions

| Component | Azure resource | Mode `vm` (default) | Mode `aks` |
|---|---|---|---|
| Resource group | `spine-hub-<bundle-id-prefix>` | ✔ | ✔ |
| Network | VNet 10.42.0.0/16 + spine-hub-subnet + NSG | ✔ | ✔ |
| Compute | Hub + Vault + Keycloak (containerised) | Standard_B2ms Ubuntu VM | AKS 1.28 (1× Standard_B2ms) |
| Postgres | Flexible Server, Burstable B1ms, private endpoint | ✔ | ✔ |
| Secrets | Key Vault (RBAC-mode) — 5 EMPTY slots seeded | ✔ | ✔ |
| Identity binding | Managed Identity on Hub VM/AKS pods → `Key Vault Secrets User` | ✔ | ✔ |
| TLS | App Gateway v2 with cert from Key Vault | ✔ | ✔ |

All resources tagged `SpineBYOC=true,SpineHubVersion=<v>,SpineBundleId=<uuid>,ManagedBy=spine-vendor`.

## 2. What the customer must grant Spine

**Delegated Admin Privileges (DAP)** via Microsoft Partner Center, scoped to a **single subscription** (NOT tenant-wide).

1. Customer's tenant admin accepts the vendor's CSP partner-relationship invite. (Vendor must already have a Cloud Solution Provider partner ID.)
2. Customer assigns DAP to vendor's `Foreign Principal for SpineHubBYOC` security group on **one subscription only**, with the `Contributor` role + `User Access Administrator` (the latter only needed to grant the Hub VM its Managed Identity role assignment in §3).
3. (Recommended) Customer enables Conditional Access requiring MFA for DAP sign-ins.

For customers without an active CSP relationship, the fallback is a **federated identity service principal** with the same Contributor + UAA scope on one subscription.

## 3. Provisioning

```bash
# 1. Stash delegated credentials in vendor vault.
spine-vault kv put kv/byoc/<subscription-guid>/azure_sp \
    tenant_id=<customer-tenant> \
    client_id=<spine-sp-client-id> \
    client_secret=<value>

# 2. Dry-run.
tools/byoc/provision.sh --non-interactive --dry-run \
    --cloud=azure --account=<customer-subscription-guid> \
    --region=westeurope --mode=vm \
    --hub-version=1.0.0 --bundle-id=$(uuidgen) \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/<subscription-guid>/azure_sp

# 3. Real run.
tools/byoc/provision.sh --non-interactive \
    --cloud=azure --account=<customer-subscription-guid> \
    --region=westeurope --mode=vm \
    --hub-version=1.0.0 --bundle-id=$(cat /tmp/bundle_id) \
    --admin-email=founder@startup.com \
    --credentials-ref=vault://kv/byoc/<subscription-guid>/azure_sp
```

## 4. Success criteria

- `az group show --name spine-hub-<bundle-id-prefix> --subscription <sub>` returns the RG
- `https://spine-hub.<customer>.azure.example/healthz` returns 200
- Customer's Key Vault has 5 slots; Hub VM's managed identity has `Key Vault Secrets User` role
- Hub Decision Queue receives a "Day-0 bootstrap complete" event tagged `cloud=azure`

## 5. Rollback / teardown

```bash
tools/byoc/provision.sh --destroy --cloud=azure \
    --account=<subscription-guid> \
    --credentials-ref=vault://kv/byoc/<subscription-guid>/azure_sp --force
```

Azure teardown is a single `az group delete --yes --no-wait` against the BYOC resource group — cascade-deletes all contained resources (network, compute, Postgres, Key Vault, App Gateway). The Key Vault soft-delete window (default 90 days) is preserved unless `--force` is set to also purge the vault.

## 6. Exit ramp (customer takes over)

1. Customer revokes DAP / unassigns vendor service principal from the subscription.
2. Hub keeps running. Customer rotates Keycloak admin via Key Vault (`spine-keycloak-admin` slot).
3. Customer takes over App Gateway DNS + cert.
4. Optional migration to Shape 3 (self-hosted AKS) via `spine export | spine import`.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `az login` succeeds but subscription not visible | DAP scope not assigned or subscription not yet propagated | wait 15 min; re-run `az account list --refresh` |
| Hub VM cannot read Key Vault | Managed Identity role assignment lagging | `az role assignment list --assignee <vm-mi-object-id>`; re-apply if missing |
| App Gateway TLS handshake fails | Cert in Key Vault not in `enabled` state | `az keyvault certificate show --vault-name <kv> --name spine-hub-cert` |
| Postgres connection times out | Private endpoint DNS not yet active | wait 10 min; `nslookup <pg-server>.postgres.database.azure.com` from Hub VM |
| `--destroy` leaves a soft-deleted Key Vault | normal Azure behavior | `az keyvault purge --name <kv> --location <region>` if customer wants the name back |

## 8. Cost guardrails

VM mode minimum monthly (westeurope):

- Standard_B2ms VM: ~$60
- Postgres Burstable B1ms: ~$13
- App Gateway v2 (small): ~$95
- Key Vault: ~$1
- VNet + NSG: free
- **Total: ~$170/mo + egress**

AKS mode adds ~$73/mo for the AKS control-plane (uptime-SLA tier). Recommend `vm` mode for Founder tier; `aks` only when the customer plans to add their own workloads to the same cluster.

## 9. References

- [`tools/byoc/provision.sh`](../provision.sh)
- [`tools/byoc/clouds/azure.sh`](../clouds/azure.sh)
- [`docs/DEPLOYMENT_SHAPES.md`](../../../docs/DEPLOYMENT_SHAPES.md)
- Microsoft DAP docs: <https://learn.microsoft.com/partner-center/customers/permissions-overview>
