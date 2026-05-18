#!/usr/bin/env bash
# tools/byoc/clouds/gcp.sh — Spine BYOC GCP provisioner.
#
# Mirrors aws.sh contract: byoc_validate_credentials / byoc_provision /
# byoc_destroy. Same dry-run-prints-plan / live-apply-scaffolded model.
#
# Modes:
#   gce  — single e2-medium Compute Engine VM (Founder default)
#   gke  — Autopilot GKE cluster (when customer wants K8s on Day 1)
#
# Drivers: docs/V3_DESIGN_DECISIONS.md §17 #20; docs/DEPLOYMENT_SHAPES.md
# §"BYOC delegation mechanism" — GCP delegation via vendor service account
# `spine-ops@<vendor>.iam.gserviceaccount.com` granted `roles/owner` (or
# narrower scoped role set) on a single project.

SPINE_BYOC_REGION="${SPINE_BYOC_REGION:-us-central1}"
SPINE_BYOC_MODE="${SPINE_BYOC_MODE:-gce}"

_gcp_log() { byoc_log "[gcp/${SPINE_BYOC_MODE}/${SPINE_BYOC_REGION}] $*"; }
_GCP_LABELS="spine-byoc=true,spine-hub-version=$(echo "${SPINE_HUB_VERSION//./_}"),managed-by=spine-vendor"

byoc_validate_credentials() {
  if ! command -v gcloud >/dev/null 2>&1; then
    _gcp_log "gcloud not on PATH — staying in STUB mode."
    export BYOC_STUB_CALLS=1
  fi
  if [[ -n "${SPINE_BYOC_CREDENTIALS_REF:-}" ]]; then
    _gcp_log "resolving credentials-ref ${SPINE_BYOC_CREDENTIALS_REF}"
    if [[ "${BYOC_STUB_CALLS:-0}" == "1" ]]; then
      _gcp_log "STUB: would resolve vault ref → SA-key JSON → gcloud auth activate-service-account --key-file=/dev/stdin"
    else
      ( byoc_resolve_vault_ref "$SPINE_BYOC_CREDENTIALS_REF" >/dev/null ) || return 3
    fi
  fi
  if [[ "${BYOC_STUB_CALLS:-0}" == "1" || "${BYOC_DRY_RUN:-0}" == "1" ]]; then
    _gcp_log "STUB: gcloud projects describe $SPINE_BYOC_ACCOUNT"
    return 0
  fi
  if ! gcloud projects describe "$SPINE_BYOC_ACCOUNT" >/dev/null 2>&1; then
    _gcp_log "FAIL: gcloud projects describe — service account lacks access to project $SPINE_BYOC_ACCOUNT"
    return 3
  fi
  return 0
}

byoc_provision() {
  byoc_banner "GCP step 1/6 — VPC + subnet + firewall rules"
  byoc_run_or_stub "create custom VPC spine-hub-vpc" \
    gcloud compute networks create spine-hub-vpc --subnet-mode=custom --project="$SPINE_BYOC_ACCOUNT"
  byoc_run_or_stub "create subnet 10.42.0.0/20 in $SPINE_BYOC_REGION" \
    gcloud compute networks subnets create spine-hub-subnet --network=spine-hub-vpc \
      --region="$SPINE_BYOC_REGION" --range=10.42.0.0/20 --project="$SPINE_BYOC_ACCOUNT"
  byoc_run_or_stub "firewall: allow tcp/443 from 0.0.0.0/0 to spine-hub tag" \
    gcloud compute firewall-rules create spine-hub-allow-443 --network=spine-hub-vpc \
      --allow=tcp:443 --target-tags=spine-hub --project="$SPINE_BYOC_ACCOUNT"
  byoc_run_or_stub "firewall: allow tcp/5432 internal-only (spine-hub tag)" \
    gcloud compute firewall-rules create spine-hub-allow-pg-internal --network=spine-hub-vpc \
      --allow=tcp:5432 --source-tags=spine-hub --target-tags=spine-db --project="$SPINE_BYOC_ACCOUNT"

  byoc_banner "GCP step 2/6 — Compute (mode=$SPINE_BYOC_MODE)"
  case "$SPINE_BYOC_MODE" in
    gce)
      byoc_run_or_stub "create e2-medium GCE VM (Container-Optimized OS, startup-script seeds Hub)" \
        gcloud compute instances create spine-hub-vm --machine-type=e2-medium \
          --image-family=cos-stable --image-project=cos-cloud --zone="${SPINE_BYOC_REGION}-a" \
          --subnet=spine-hub-subnet --tags=spine-hub \
          --service-account="spine-hub-vm@${SPINE_BYOC_ACCOUNT}.iam.gserviceaccount.com" \
          --scopes=cloud-platform --labels="$_GCP_LABELS" --project="$SPINE_BYOC_ACCOUNT"
      ;;
    gke)
      byoc_run_or_stub "create GKE Autopilot cluster spine-hub (Workload Identity ON for vault adapter)" \
        gcloud container clusters create-auto spine-hub --region="$SPINE_BYOC_REGION" \
          --network=spine-hub-vpc --subnetwork=spine-hub-subnet \
          --workload-pool="${SPINE_BYOC_ACCOUNT}.svc.id.goog" --project="$SPINE_BYOC_ACCOUNT"
      ;;
    *)
      BYOC_DIE_CODE=6 byoc_die "GCP --mode must be gce or gke (got $SPINE_BYOC_MODE)"
      ;;
  esac

  byoc_banner "GCP step 3/6 — Postgres (Cloud SQL db-f1-micro, private IP only)"
  byoc_run_or_stub "create Cloud SQL spine-hub-pg (private-IP, managed password)" \
    gcloud sql instances create "spine-hub-pg-${SPINE_BYOC_BUNDLE_ID:0:6}" \
      --database-version=POSTGRES_16 --tier=db-f1-micro --region="$SPINE_BYOC_REGION" \
      --network=spine-hub-vpc --no-assign-ip --backup --enable-point-in-time-recovery \
      --project="$SPINE_BYOC_ACCOUNT"

  byoc_banner "GCP step 4/6 — Secret Manager (vault adapter; Workload Identity binding)"
  for slot in spine-license-bundle spine-keycloak-admin spine-db-password \
              spine-vault-root-token spine-oidc-client-secret; do
    byoc_run_or_stub "create EMPTY Secret Manager secret: $slot" \
      gcloud secrets create "$slot" --replication-policy=automatic \
        --labels="$_GCP_LABELS" --project="$SPINE_BYOC_ACCOUNT"
  done
  if [[ "$SPINE_BYOC_MODE" == "gke" ]]; then
    byoc_run_or_stub "bind k8s SA 'spine-hub' → IAM SA via Workload Identity" \
      gcloud iam service-accounts add-iam-policy-binding \
        "spine-hub@${SPINE_BYOC_ACCOUNT}.iam.gserviceaccount.com" \
        --role=roles/iam.workloadIdentityUser \
        --member="serviceAccount:${SPINE_BYOC_ACCOUNT}.svc.id.goog[spine/spine-hub]" \
        --project="$SPINE_BYOC_ACCOUNT"
  fi

  byoc_banner "GCP step 5/6 — TLS (managed cert via GCLB or VM-resident cert-manager)"
  byoc_run_or_stub "reserve static external IP + managed certificate" \
    gcloud compute addresses create spine-hub-ip --global --project="$SPINE_BYOC_ACCOUNT"

  byoc_banner "GCP step 6/6 — Seed Hub + wizard"
  _gcp_log "[stub] gcloud compute ssh spine-hub-vm --zone=${SPINE_BYOC_REGION}-a -- \\"
  _gcp_log "  bash /opt/spine/hub/wizard/init.sh --non-interactive --deployment-shape=byoc \\"
  _gcp_log "  --vault-adapter=gcp --keycloak=bundled --llm-provider=anthropic \\"
  _gcp_log "  --admin-email=${SPINE_BYOC_ADMIN_EMAIL} \\"
  _gcp_log "  --admin-password-from-vault-path=spine-keycloak-admin"

  byoc_emit_handoff \
    "https://spine-hub.${SPINE_BYOC_ACCOUNT}.gcp.example" \
    "$SPINE_BYOC_ADMIN_EMAIL" \
    "GCP Secret Manager: projects/${SPINE_BYOC_ACCOUNT}/secrets/spine-vault-unseal-shares"
}

byoc_destroy() {
  byoc_banner "GCP teardown — reverse order"
  case "$SPINE_BYOC_MODE" in
    gke)
      byoc_run_or_stub "delete GKE cluster spine-hub" \
        gcloud container clusters delete spine-hub --region="$SPINE_BYOC_REGION" --project="$SPINE_BYOC_ACCOUNT" --quiet
      ;;
    gce|*)
      byoc_run_or_stub "delete GCE VM spine-hub-vm" \
        gcloud compute instances delete spine-hub-vm --zone="${SPINE_BYOC_REGION}-a" --project="$SPINE_BYOC_ACCOUNT" --quiet
      ;;
  esac
  byoc_run_or_stub "delete Cloud SQL instance" \
    gcloud sql instances delete "spine-hub-pg-${SPINE_BYOC_BUNDLE_ID:0:6}" --project="$SPINE_BYOC_ACCOUNT" --quiet
  byoc_run_or_stub "delete Secret Manager slots" \
    gcloud secrets delete spine-license-bundle --project="$SPINE_BYOC_ACCOUNT" --quiet
  byoc_run_or_stub "delete firewall rules + subnet + VPC" \
    gcloud compute networks delete spine-hub-vpc --project="$SPINE_BYOC_ACCOUNT" --quiet
  _gcp_log "GCP teardown complete. Confirm with: gcloud compute networks list --filter='name=spine-hub-vpc' --project=$SPINE_BYOC_ACCOUNT"
}
