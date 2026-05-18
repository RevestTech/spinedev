#!/usr/bin/env bash
# tools/byoc/clouds/azure.sh — Spine BYOC Azure provisioner.
#
# Mirrors tools/byoc/clouds/aws.sh contract:
#   byoc_validate_credentials / byoc_provision / byoc_destroy.
#
# Modes (--mode):
#   vm   — single Standard_B2ms VM (Founder default, cheapest)
#   aks  — single-node AKS 1.28 (when customer wants K8s on Day 1)
#
# v1.0 completeness: --dry-run prints the full plan; live apply is
# scaffolded. Real `az group create / vm create / aks create` calls are
# stubbed unless `az` is on PATH AND BYOC_STUB_CALLS != 1.
#
# Drivers: docs/V3_DESIGN_DECISIONS.md §17 #20; docs/DEPLOYMENT_SHAPES.md
# §"BYOC delegation mechanism" — Azure delegation via Microsoft Partner
# Center Delegated Admin Privileges (DAP) on a single subscription.

SPINE_BYOC_REGION="${SPINE_BYOC_REGION:-westeurope}"
SPINE_BYOC_MODE="${SPINE_BYOC_MODE:-vm}"

_az_log() { byoc_log "[azure/${SPINE_BYOC_MODE}/${SPINE_BYOC_REGION}] $*"; }

_AZ_TAGS="SpineBYOC=true SpineHubVersion=${SPINE_HUB_VERSION} SpineBundleId=${SPINE_BYOC_BUNDLE_ID} ManagedBy=spine-vendor"
_AZ_RG="spine-hub-${SPINE_BYOC_BUNDLE_ID:0:8}"

byoc_validate_credentials() {
  if ! command -v az >/dev/null 2>&1; then
    _az_log "az CLI not on PATH — staying in STUB mode."
    export BYOC_STUB_CALLS=1
  fi
  if [[ -n "${SPINE_BYOC_CREDENTIALS_REF:-}" ]]; then
    _az_log "resolving credentials-ref ${SPINE_BYOC_CREDENTIALS_REF}"
    if [[ "${BYOC_STUB_CALLS:-0}" == "1" ]]; then
      _az_log "STUB: would resolve vault ref → service-principal JSON → az login --service-principal"
    else
      ( byoc_resolve_vault_ref "$SPINE_BYOC_CREDENTIALS_REF" >/dev/null ) || return 3
    fi
  fi
  if [[ "${BYOC_STUB_CALLS:-0}" == "1" || "${BYOC_DRY_RUN:-0}" == "1" ]]; then
    _az_log "STUB: az account show --subscription $SPINE_BYOC_ACCOUNT"
    return 0
  fi
  if ! az account show --subscription "$SPINE_BYOC_ACCOUNT" >/dev/null 2>&1; then
    _az_log "FAIL: az account show — DAP not assumable for subscription $SPINE_BYOC_ACCOUNT"
    return 3
  fi
  return 0
}

byoc_provision() {
  byoc_banner "Azure step 1/6 — Resource Group + VNet + Subnets + NSG"
  byoc_run_or_stub "create resource group $_AZ_RG" \
    az group create --name "$_AZ_RG" --location "$SPINE_BYOC_REGION" --tags $_AZ_TAGS --subscription "$SPINE_BYOC_ACCOUNT"
  byoc_run_or_stub "create VNet 10.42.0.0/16" \
    az network vnet create -g "$_AZ_RG" --name spine-hub-vnet --address-prefix 10.42.0.0/16 \
      --subnet-name spine-hub-subnet --subnet-prefix 10.42.1.0/24 --subscription "$SPINE_BYOC_ACCOUNT"
  byoc_run_or_stub "create NSG with 443/80 ingress" \
    az network nsg create -g "$_AZ_RG" --name spine-hub-nsg --subscription "$SPINE_BYOC_ACCOUNT"
  byoc_run_or_stub "allow tcp/443 from internet to spine-hub-nsg" \
    az network nsg rule create -g "$_AZ_RG" --nsg-name spine-hub-nsg --name allow-443 \
      --priority 100 --destination-port-ranges 443 --access Allow --protocol Tcp --subscription "$SPINE_BYOC_ACCOUNT"

  byoc_banner "Azure step 2/6 — Compute (mode=$SPINE_BYOC_MODE)"
  case "$SPINE_BYOC_MODE" in
    vm)
      byoc_run_or_stub "create Standard_B2ms VM (Ubuntu 22.04 LTS, cloud-init seeds Hub)" \
        az vm create -g "$_AZ_RG" --name spine-hub-vm --image Ubuntu2204 \
          --size Standard_B2ms --vnet-name spine-hub-vnet --subnet spine-hub-subnet \
          --nsg spine-hub-nsg --assign-identity --custom-data file:///dev/stdin \
          --subscription "$SPINE_BYOC_ACCOUNT"
      ;;
    aks)
      byoc_run_or_stub "create AKS spine-hub (1.28, 1×Standard_B2ms)" \
        az aks create -g "$_AZ_RG" --name spine-hub --kubernetes-version 1.28 \
          --node-count 1 --node-vm-size Standard_B2ms --enable-managed-identity \
          --network-plugin azure --vnet-subnet-id "/subscriptions/$SPINE_BYOC_ACCOUNT/.../spine-hub-subnet" \
          --subscription "$SPINE_BYOC_ACCOUNT"
      ;;
    *)
      BYOC_DIE_CODE=6 byoc_die "Azure --mode must be vm or aks (got $SPINE_BYOC_MODE)"
      ;;
  esac

  byoc_banner "Azure step 3/6 — Postgres (Flexible Server, Burstable B1ms, internal-only)"
  byoc_run_or_stub "create Postgres Flexible Server (managed admin password)" \
    az postgres flexible-server create -g "$_AZ_RG" --name "spine-hub-pg-${SPINE_BYOC_BUNDLE_ID:0:6}" \
      --location "$SPINE_BYOC_REGION" --tier Burstable --sku-name Standard_B1ms \
      --storage-size 32 --version 16 --vnet spine-hub-vnet --subnet spine-hub-subnet \
      --public-access None --subscription "$SPINE_BYOC_ACCOUNT"

  byoc_banner "Azure step 4/6 — Key Vault (vault adapter integration per #9)"
  byoc_run_or_stub "create Key Vault spine-hub-kv-<bundleid>" \
    az keyvault create -g "$_AZ_RG" --name "spine-hub-kv-${SPINE_BYOC_BUNDLE_ID:0:6}" \
      --location "$SPINE_BYOC_REGION" --enable-rbac-authorization true --subscription "$SPINE_BYOC_ACCOUNT"
  for slot in spine-license-bundle spine-keycloak-admin spine-db-password spine-vault-root-token spine-oidc-client-secret; do
    byoc_run_or_stub "create EMPTY Key Vault secret slot: $slot" \
      az keyvault secret set --vault-name "spine-hub-kv-${SPINE_BYOC_BUNDLE_ID:0:6}" \
        --name "$slot" --value "__SET_BY_HUB__" --subscription "$SPINE_BYOC_ACCOUNT"
  done
  byoc_run_or_stub "grant Hub managed identity → 'Key Vault Secrets User' role on the KV" \
    az role assignment create --assignee-object-id "<hub-vm-managed-identity>" \
      --role "Key Vault Secrets User" \
      --scope "/subscriptions/$SPINE_BYOC_ACCOUNT/resourceGroups/$_AZ_RG/providers/Microsoft.KeyVault/vaults/spine-hub-kv-${SPINE_BYOC_BUNDLE_ID:0:6}"

  byoc_banner "Azure step 5/6 — App Gateway + TLS (cert from KV)"
  byoc_run_or_stub "create Application Gateway spine-hub-agw + TLS listener from KV cert" \
    az network application-gateway create -g "$_AZ_RG" --name spine-hub-agw \
      --location "$SPINE_BYOC_REGION" --sku Standard_v2 --vnet-name spine-hub-vnet --subnet spine-hub-subnet \
      --public-ip-address spine-hub-pip --servers "<hub-vm-ip>" --subscription "$SPINE_BYOC_ACCOUNT"

  byoc_banner "Azure step 6/6 — Seed Hub + wizard"
  _az_log "[stub] ssh azureuser@<vm-ip> -- bash /opt/spine/hub/wizard/init.sh \\"
  _az_log "  --non-interactive --deployment-shape=byoc --vault-adapter=azure \\"
  _az_log "  --keycloak=bundled --llm-provider=anthropic \\"
  _az_log "  --admin-email=${SPINE_BYOC_ADMIN_EMAIL} \\"
  _az_log "  --admin-password-from-vault-path=spine-keycloak-admin"

  byoc_emit_handoff \
    "https://spine-hub.${SPINE_BYOC_ACCOUNT}.azure.example" \
    "$SPINE_BYOC_ADMIN_EMAIL" \
    "Azure Key Vault: spine-hub-kv-${SPINE_BYOC_BUNDLE_ID:0:6}/spine-vault-unseal-shares"
}

byoc_destroy() {
  byoc_banner "Azure teardown — resource-group cascade delete"
  byoc_run_or_stub "delete resource group $_AZ_RG (cascade)" \
    az group delete --name "$_AZ_RG" --yes --no-wait --subscription "$SPINE_BYOC_ACCOUNT"
  _az_log "Azure teardown initiated. Confirm with: az group show --name $_AZ_RG"
}
