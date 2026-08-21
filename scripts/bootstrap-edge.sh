#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-flexbone-ocr}"
DOMAIN="${DOMAIN:-api.ocr.lelbaba.top}"
RATE_LIMIT_PREVIEW="${RATE_LIMIT_PREVIEW:-true}"

NEG="${SERVICE}-neg"
BACKEND="${SERVICE}-backend"
POLICY="${SERVICE}-edge"
ADDRESS="${SERVICE}-ip"
URL_MAP="${SERVICE}-url-map"
HTTPS_PROXY="${SERVICE}-https-proxy"
FORWARDING_RULE="${SERVICE}-https"
DNS_AUTHORIZATION="${SERVICE}-domain"
CERTIFICATE="${SERVICE}-certificate"
CERTIFICATE_MAP="${SERVICE}-certificate-map"
CERTIFICATE_ENTRY="${SERVICE}-certificate-entry"

gcloud config set project "$PROJECT_ID"
gcloud services enable compute.googleapis.com certificatemanager.googleapis.com

gcloud compute addresses describe "$ADDRESS" --global >/dev/null 2>&1 || \
  gcloud compute addresses create "$ADDRESS" --global --ip-version IPV4 --network-tier PREMIUM

gcloud compute network-endpoint-groups describe "$NEG" --region "$REGION" >/dev/null 2>&1 || \
  gcloud compute network-endpoint-groups create "$NEG" \
    --region "$REGION" \
    --network-endpoint-type serverless \
    --cloud-run-service "$SERVICE"

gcloud compute backend-services describe "$BACKEND" --global >/dev/null 2>&1 || \
  gcloud compute backend-services create "$BACKEND" \
    --global \
    --load-balancing-scheme EXTERNAL_MANAGED \
    --protocol HTTP \
    --timeout 60s

if ! gcloud compute backend-services describe "$BACKEND" --global --format=json | \
  jq -e --arg suffix "/regions/$REGION/networkEndpointGroups/$NEG" \
    'any(.backends[]?; .group | endswith($suffix))' >/dev/null; then
  gcloud compute backend-services add-backend "$BACKEND" \
    --global \
    --network-endpoint-group "$NEG" \
    --network-endpoint-group-region "$REGION"
fi

gcloud compute backend-services update "$BACKEND" \
  --global \
  --enable-logging \
  --logging-sample-rate 1.0

gcloud compute security-policies describe "$POLICY" >/dev/null 2>&1 || \
  gcloud compute security-policies create "$POLICY" \
    --type CLOUD_ARMOR \
    --description "OCR API edge policy"

if [[ "$RATE_LIMIT_PREVIEW" == "true" ]]; then
  preview_flag="--preview"
else
  preview_flag="--no-preview"
fi

upsert_rate_rule() {
  local priority="$1"
  local expression="$2"
  local request_count="$3"
  local description="$4"
  local command="create"
  if gcloud compute security-policies rules describe "$priority" \
    --security-policy "$POLICY" >/dev/null 2>&1; then
    command="update"
  fi
  gcloud compute security-policies rules "$command" "$priority" \
    --security-policy "$POLICY" \
    --expression "$expression" \
    --action throttle \
    --rate-limit-threshold-count "$request_count" \
    --rate-limit-threshold-interval-sec 60 \
    --conform-action allow \
    --exceed-action deny-429 \
    --enforce-on-key IP \
    --description "$description" \
    "$preview_flag"
}

upsert_rate_rule 1000 \
  "request.method == 'POST' && request.path == '/extract-text/batch'" \
  2 \
  "Two batch requests per minute per IP"
upsert_rate_rule 1100 \
  "request.method == 'POST' && request.path == '/extract-text'" \
  10 \
  "Ten single requests per minute per IP"

gcloud compute backend-services update "$BACKEND" \
  --global \
  --security-policy "$POLICY"

gcloud certificate-manager dns-authorizations describe "$DNS_AUTHORIZATION" >/dev/null 2>&1 || \
  gcloud certificate-manager dns-authorizations create "$DNS_AUTHORIZATION" \
    --domain "$DOMAIN" \
    --type per-project-record

gcloud certificate-manager certificates describe "$CERTIFICATE" >/dev/null 2>&1 || \
  gcloud certificate-manager certificates create "$CERTIFICATE" \
    --domains "$DOMAIN" \
    --dns-authorizations "$DNS_AUTHORIZATION"

gcloud certificate-manager maps describe "$CERTIFICATE_MAP" >/dev/null 2>&1 || \
  gcloud certificate-manager maps create "$CERTIFICATE_MAP"
gcloud certificate-manager maps entries describe "$CERTIFICATE_ENTRY" \
  --map "$CERTIFICATE_MAP" >/dev/null 2>&1 || \
  gcloud certificate-manager maps entries create "$CERTIFICATE_ENTRY" \
    --map "$CERTIFICATE_MAP" \
    --hostname "$DOMAIN" \
    --certificates "$CERTIFICATE"

gcloud compute url-maps describe "$URL_MAP" --global >/dev/null 2>&1 || \
  gcloud compute url-maps create "$URL_MAP" \
    --global \
    --default-service "$BACKEND"
gcloud compute url-maps set-default-service "$URL_MAP" \
  --global \
  --default-service "$BACKEND"

gcloud compute target-https-proxies describe "$HTTPS_PROXY" --global >/dev/null 2>&1 || \
  gcloud compute target-https-proxies create "$HTTPS_PROXY" \
    --global \
    --url-map "$URL_MAP" \
    --certificate-map "$CERTIFICATE_MAP"
gcloud compute target-https-proxies update "$HTTPS_PROXY" \
  --global \
  --url-map "$URL_MAP" \
  --certificate-map "$CERTIFICATE_MAP"

gcloud compute forwarding-rules describe "$FORWARDING_RULE" --global >/dev/null 2>&1 || \
  gcloud compute forwarding-rules create "$FORWARDING_RULE" \
    --global \
    --load-balancing-scheme EXTERNAL_MANAGED \
    --network-tier PREMIUM \
    --address "$ADDRESS" \
    --target-https-proxy "$HTTPS_PROXY" \
    --ports 443

dns_name="$(gcloud certificate-manager dns-authorizations describe "$DNS_AUTHORIZATION" --format='value(dnsResourceRecord.name)')"
dns_target="$(gcloud certificate-manager dns-authorizations describe "$DNS_AUTHORIZATION" --format='value(dnsResourceRecord.data)')"
load_balancer_ip="$(gcloud compute addresses describe "$ADDRESS" --global --format='value(address)')"

printf 'CERTIFICATE_CNAME_NAME=%s\n' "$dns_name"
printf 'CERTIFICATE_CNAME_TARGET=%s\n' "$dns_target"
printf 'LOAD_BALANCER_IP=%s\n' "$load_balancer_ip"
printf 'RATE_LIMIT_PREVIEW=%s\n' "$RATE_LIMIT_PREVIEW"
