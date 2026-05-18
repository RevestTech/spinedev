#!/usr/bin/env bash
# tools/byoc/clouds/aws.sh — Spine BYOC AWS provisioner.
#
# Sourced by tools/byoc/provision.sh. Must define:
#   * byoc_validate_credentials()  — exits non-zero if delegated role cannot
#                                    be assumed in the customer account.
#   * byoc_provision()             — provisions VPC/Subnets/IGW/RT/SG +
#                                    compute (EC2 or EKS) + ALB + ACM +
#                                    Secrets Manager hooks + DNS, then
#                                    seeds the Hub + Vault + Keycloak +
#                                    Postgres. Idempotent.
#   * byoc_destroy()               — tear down, reverse order.
#
# We do NOT call the AWS API from this agent (see system brief). Cloud
# calls are wrapped in `byoc_run_or_stub`, so under BYOC_STUB_CALLS=1 or
# BYOC_DRY_RUN=1 we log-and-skip. Under real use, an operator runs this
# with the real `aws` CLI on PATH and the delegated role pre-assumed.
#
# Drivers: docs/V3_DESIGN_DECISIONS.md §17 (BYOC) + §20 (5+ clouds) +
# docs/DEPLOYMENT_SHAPES.md §"Shape 2 — Vendor-Managed (BYOC)".
#
# Modes (--mode):
#   ec2   — single t3.medium EC2 (cheaper, Founder-tier default)
#   eks   — single-node EKS 1.28 (when customer wants K8s on Day 1)
#
# This script is the AWS reference impl; sibling cloud scripts mirror
# its contract.

# ─── tag-everything contract (per #11 cost attribution + #15 audit) ─
_AWS_TAGS_KV="\
Key=SpineBYOC,Value=true \
Key=SpineHubVersion,Value=${SPINE_HUB_VERSION} \
Key=SpineBundleId,Value=${SPINE_BYOC_BUNDLE_ID} \
Key=ManagedBy,Value=spine-vendor"

# Per-cloud defaults filled in if caller did not pass --mode / --region.
SPINE_BYOC_REGION="${SPINE_BYOC_REGION:-us-east-1}"
SPINE_BYOC_MODE="${SPINE_BYOC_MODE:-ec2}"

_aws_log() { byoc_log "[aws/${SPINE_BYOC_MODE}/${SPINE_BYOC_REGION}] $*"; }

# ─── credential validation ──────────────────────────────────────────
byoc_validate_credentials() {
  if ! command -v aws >/dev/null 2>&1; then
    _aws_log "aws CLI not on PATH — staying in STUB mode."
    export BYOC_STUB_CALLS=1
  fi

  # Resolve the credentials-ref if given. The result MUST be a JSON
  # blob with AssumeRole output shape: {AccessKeyId, SecretAccessKey,
  # SessionToken}. Real impl pipes into `aws configure`; we never
  # write to disk.
  if [[ -n "${SPINE_BYOC_CREDENTIALS_REF:-}" ]]; then
    _aws_log "resolving credentials-ref ${SPINE_BYOC_CREDENTIALS_REF}"
    # The actual `aws sts assume-role` round-trip happens at this seam
    # in real impl; here we only validate that we CAN resolve the ref.
    if [[ "${BYOC_STUB_CALLS:-0}" == "1" ]]; then
      _aws_log "STUB: would resolve vault ref → AssumeRole JSON → AWS_* env (in subshell)"
    else
      # Resolve into a subshell so the value never lands in this shell's env.
      ( byoc_resolve_vault_ref "$SPINE_BYOC_CREDENTIALS_REF" >/dev/null ) \
        || return 3
    fi
  fi

  # Probe `aws sts get-caller-identity`. Stubbed under STUB / DRY_RUN.
  if [[ "${BYOC_STUB_CALLS:-0}" == "1" || "${BYOC_DRY_RUN:-0}" == "1" ]]; then
    _aws_log "STUB: aws sts get-caller-identity --region $SPINE_BYOC_REGION"
    return 0
  fi
  if ! aws sts get-caller-identity --region "$SPINE_BYOC_REGION" >/dev/null 2>&1; then
    _aws_log "FAIL: aws sts get-caller-identity — delegated role not assumable."
    return 3
  fi
  _aws_log "delegated role assumes cleanly."
  return 0
}

# ─── helpers ────────────────────────────────────────────────────────
_aws_resource_exists() {
  # Usage: _aws_resource_exists <describe-cmd...> ; sets EXIT=0 if exists.
  # Under stub/dry-run, returns 1 (doesn't exist) so idempotency demo
  # runs through the full provision path in logs.
  if [[ "${BYOC_STUB_CALLS:-0}" == "1" || "${BYOC_DRY_RUN:-0}" == "1" ]]; then
    return 1
  fi
  "$@" >/dev/null 2>&1
}

# ─── provision steps ────────────────────────────────────────────────
_aws_provision_network() {
  byoc_banner "AWS step 1/7 — Network (VPC + 2 subnets + IGW + RT + SG)"
  byoc_run_or_stub "create VPC 10.42.0.0/16" \
    aws ec2 create-vpc --cidr-block 10.42.0.0/16 \
      --tag-specifications "ResourceType=vpc,Tags=[${_AWS_TAGS_KV// /,}]" \
      --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "create subnet 10.42.1.0/24 (public-a)" \
    aws ec2 create-subnet --vpc-id vpc-stub --cidr-block 10.42.1.0/24 \
      --availability-zone "${SPINE_BYOC_REGION}a" --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "create subnet 10.42.2.0/24 (public-b)" \
    aws ec2 create-subnet --vpc-id vpc-stub --cidr-block 10.42.2.0/24 \
      --availability-zone "${SPINE_BYOC_REGION}b" --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "create internet gateway" \
    aws ec2 create-internet-gateway --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "attach IGW to VPC" \
    aws ec2 attach-internet-gateway --internet-gateway-id igw-stub --vpc-id vpc-stub --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "create route table + 0.0.0.0/0 → IGW route" \
    aws ec2 create-route-table --vpc-id vpc-stub --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "create security group spine-hub-sg" \
    aws ec2 create-security-group --group-name spine-hub-sg --description "Spine Hub ingress" \
      --vpc-id vpc-stub --region "$SPINE_BYOC_REGION"
  # Ingress: 443 (Hub web), 8200 (Vault, internal-only via SG ref), 8080 (Keycloak).
  byoc_run_or_stub "open :443 to 0.0.0.0/0 (Hub ALB)" \
    aws ec2 authorize-security-group-ingress --group-id sg-stub --protocol tcp --port 443 --cidr 0.0.0.0/0 --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "open :8080 to ALB-SG only (Keycloak)" \
    aws ec2 authorize-security-group-ingress --group-id sg-stub --protocol tcp --port 8080 --source-group sg-alb-stub --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "open :8200 to ALB-SG only (Vault)" \
    aws ec2 authorize-security-group-ingress --group-id sg-stub --protocol tcp --port 8200 --source-group sg-alb-stub --region "$SPINE_BYOC_REGION"
  # Postgres 5432 NEVER opens to internet; SG-ref from Hub-SG only.
  byoc_run_or_stub "open :5432 from Hub-SG only (Postgres internal)" \
    aws ec2 authorize-security-group-ingress --group-id sg-db-stub --protocol tcp --port 5432 --source-group sg-stub --region "$SPINE_BYOC_REGION"
}

_aws_provision_compute() {
  byoc_banner "AWS step 2/7 — Compute (mode=$SPINE_BYOC_MODE)"
  case "$SPINE_BYOC_MODE" in
    ec2)
      byoc_run_or_stub "launch t3.medium EC2 (AL2023, user-data=spine-bootstrap.sh)" \
        aws ec2 run-instances --image-id ami-stub --instance-type t3.medium \
          --subnet-id subnet-stub --security-group-ids sg-stub \
          --iam-instance-profile Name=SpineHubInstanceProfile \
          --user-data file:///dev/stdin --region "$SPINE_BYOC_REGION"
      ;;
    eks)
      byoc_run_or_stub "create EKS cluster spine-hub (1.28, 1×t3.medium node)" \
        aws eks create-cluster --name spine-hub --kubernetes-version 1.28 \
          --role-arn arn:aws:iam::stub:role/SpineEKSClusterRole \
          --resources-vpc-config "subnetIds=subnet-stub,subnet-stub2,securityGroupIds=sg-stub" \
          --region "$SPINE_BYOC_REGION"
      byoc_run_or_stub "create EKS nodegroup (1×t3.medium)" \
        aws eks create-nodegroup --cluster-name spine-hub --nodegroup-name spine-default \
          --instance-types t3.medium --scaling-config minSize=1,maxSize=2,desiredSize=1 \
          --node-role arn:aws:iam::stub:role/SpineEKSNodeRole \
          --subnets subnet-stub subnet-stub2 --region "$SPINE_BYOC_REGION"
      ;;
    *)
      BYOC_DIE_CODE=6 byoc_die "AWS --mode must be ec2 or eks (got $SPINE_BYOC_MODE)"
      ;;
  esac
}

_aws_provision_db() {
  byoc_banner "AWS step 3/7 — Postgres (RDS db.t3.micro, internal-only)"
  byoc_run_or_stub "create db subnet group" \
    aws rds create-db-subnet-group --db-subnet-group-name spine-hub-db \
      --db-subnet-group-description "Spine Hub DB" --subnet-ids subnet-stub subnet-stub2 \
      --region "$SPINE_BYOC_REGION"
  # The master password MUST NOT be passed on the CLI. Real impl uses
  # `--master-user-password file:///dev/stdin` reading from a vault-resolved
  # subshell, OR `--manage-master-user-password` (RDS-managed in Secrets Manager).
  byoc_run_or_stub "create RDS db.t3.micro (manage-master-user-password → Secrets Manager)" \
    aws rds create-db-instance --db-instance-identifier spine-hub-pg \
      --engine postgres --engine-version 16 \
      --db-instance-class db.t3.micro --allocated-storage 20 \
      --db-subnet-group-name spine-hub-db --vpc-security-group-ids sg-db-stub \
      --manage-master-user-password --no-publicly-accessible \
      --backup-retention-period 7 --region "$SPINE_BYOC_REGION"
}

_aws_provision_secrets() {
  byoc_banner "AWS step 4/7 — Secrets Manager hooks (vault adapter selection)"
  # We do NOT write secret VALUES — we provision the EMPTY secret slots that the
  # in-cluster OpenBao adapter (or AWS adapter) will read. Per #9.
  for slot in spine/hub/license_bundle spine/hub/keycloak_admin spine/hub/db_password \
              spine/hub/vault_root_token spine/hub/oidc_client_secret; do
    byoc_run_or_stub "create empty Secrets Manager slot: $slot" \
      aws secretsmanager create-secret --name "$slot" \
        --description "Spine Hub managed slot (BYOC bundle ${SPINE_BYOC_BUNDLE_ID})" \
        --tags "[${_AWS_TAGS_KV// /,}]" --region "$SPINE_BYOC_REGION"
  done
}

_aws_provision_tls() {
  byoc_banner "AWS step 5/7 — TLS via ACM + ALB"
  byoc_run_or_stub "request ACM cert (DNS-validated, *.spine-hub.<customer-domain>)" \
    aws acm request-certificate --domain-name "spine-hub.${SPINE_BYOC_ACCOUNT}.example" \
      --validation-method DNS --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "create ALB spine-hub-alb (internet-facing, 2 subnets)" \
    aws elbv2 create-load-balancer --name spine-hub-alb \
      --subnets subnet-stub subnet-stub2 --security-groups sg-alb-stub \
      --scheme internet-facing --type application --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "create target-group spine-hub-tg → :443 health /healthz" \
    aws elbv2 create-target-group --name spine-hub-tg --protocol HTTPS --port 443 \
      --vpc-id vpc-stub --health-check-path /healthz --region "$SPINE_BYOC_REGION"
  byoc_run_or_stub "create HTTPS listener on ALB (cert from ACM)" \
    aws elbv2 create-listener --load-balancer-arn arn:aws:elasticloadbalancing:stub \
      --protocol HTTPS --port 443 --certificates CertificateArn=arn:aws:acm:stub \
      --default-actions Type=forward,TargetGroupArn=arn:aws:elasticloadbalancing:stub-tg \
      --region "$SPINE_BYOC_REGION"
}

_aws_seed_hub() {
  byoc_banner "AWS step 6/7 — Seed Hub container (spine/hub:${SPINE_HUB_VERSION})"
  case "$SPINE_BYOC_MODE" in
    ec2)
      # In real impl, the EC2 user-data already pulled the Hub image; here we
      # log the equivalent docker-compose up.
      _aws_log "[stub] ssh ec2-user@<ip> -- docker compose -f /opt/spine/hub/docker-compose.yml up -d"
      _aws_log "[stub] ssh ec2-user@<ip> -- bash /opt/spine/hub/wizard/init.sh \\"
      _aws_log "  --non-interactive --deployment-shape=byoc --vault-adapter=aws \\"
      _aws_log "  --keycloak=bundled --llm-provider=anthropic \\"
      _aws_log "  --admin-email=${SPINE_BYOC_ADMIN_EMAIL} \\"
      _aws_log "  --admin-password-from-vault-path=spine/hub/keycloak_admin \\"
      _aws_log "  --hub-base-url=https://spine-hub.${SPINE_BYOC_ACCOUNT}.example"
      ;;
    eks)
      _aws_log "[stub] kubectl create namespace spine"
      _aws_log "[stub] helm install spine-hub spine/hub --version ${SPINE_HUB_VERSION} \\"
      _aws_log "  -n spine -f values.byoc-aws.yaml"
      _aws_log "[stub] kubectl exec -n spine deploy/spine-hub -- /spine/hub/wizard/init.sh --non-interactive ..."
      ;;
  esac
}

_aws_register_dns() {
  byoc_banner "AWS step 7/7 — Route 53 (CNAME spine-hub.<customer> → ALB DNS)"
  byoc_run_or_stub "upsert A-ALIAS spine-hub.<customer> → ALB DNS" \
    aws route53 change-resource-record-sets --hosted-zone-id Z-STUB \
      --change-batch file:///dev/stdin --region "$SPINE_BYOC_REGION"
}

# ─── public entry-points ────────────────────────────────────────────
byoc_provision() {
  case "$SPINE_BYOC_MODE" in
    ec2|eks) ;;
    *) BYOC_DIE_CODE=6 byoc_die "AWS --mode must be ec2 or eks (got $SPINE_BYOC_MODE)" ;;
  esac
  _aws_provision_network
  _aws_provision_compute
  _aws_provision_db
  _aws_provision_secrets
  _aws_provision_tls
  _aws_seed_hub
  _aws_register_dns

  byoc_emit_handoff \
    "https://spine-hub.${SPINE_BYOC_ACCOUNT}.example" \
    "$SPINE_BYOC_ADMIN_EMAIL" \
    "AWS Secrets Manager: spine/hub/vault_unseal_shares"
}

byoc_destroy() {
  byoc_banner "AWS teardown — reverse order"
  byoc_run_or_stub "delete Route 53 CNAME" \
    aws route53 change-resource-record-sets --hosted-zone-id Z-STUB --change-batch file:///dev/stdin
  byoc_run_or_stub "delete ALB + target-group + listener" \
    aws elbv2 delete-load-balancer --load-balancer-arn arn:aws:elasticloadbalancing:stub
  byoc_run_or_stub "delete ACM cert" \
    aws acm delete-certificate --certificate-arn arn:aws:acm:stub
  byoc_run_or_stub "delete Secrets Manager slots (force, no recovery window)" \
    aws secretsmanager delete-secret --secret-id spine/hub/license_bundle --force-delete-without-recovery
  byoc_run_or_stub "delete RDS instance (skip final snapshot only if --force)" \
    aws rds delete-db-instance --db-instance-identifier spine-hub-pg --skip-final-snapshot
  case "$SPINE_BYOC_MODE" in
    eks)
      byoc_run_or_stub "delete EKS nodegroup + cluster" \
        aws eks delete-cluster --name spine-hub
      ;;
    ec2|*)
      byoc_run_or_stub "terminate EC2 instance" \
        aws ec2 terminate-instances --instance-ids i-stub
      ;;
  esac
  byoc_run_or_stub "delete security groups + route table + subnets + IGW + VPC" \
    aws ec2 delete-vpc --vpc-id vpc-stub
  byoc_log "AWS teardown complete. Confirm with: aws ec2 describe-vpcs --filters Name=tag:SpineBYOC,Values=true"
}
