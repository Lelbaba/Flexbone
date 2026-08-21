#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
: "${GITHUB_REPOSITORY:?Set GITHUB_REPOSITORY (owner/repo)}"
REGION="${REGION:-asia-south1}"
REPOSITORY="${REPOSITORY:-flexbone}"
RUNTIME_SA="ocr-runtime"
DEPLOY_SA="ocr-deployer"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com vision.googleapis.com iamcredentials.googleapis.com sts.googleapis.com serviceusage.googleapis.com cloudresourcemanager.googleapis.com
gcloud artifacts repositories describe "$REPOSITORY" --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPOSITORY" --repository-format docker --location "$REGION"
gcloud iam service-accounts describe "$RUNTIME_SA@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$RUNTIME_SA"
gcloud iam service-accounts describe "$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$DEPLOY_SA"

gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$RUNTIME_SA@$PROJECT_ID.iam.gserviceaccount.com" --role roles/serviceusage.serviceUsageConsumer
gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY" --location "$REGION" --member "serviceAccount:$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com" --role roles/artifactregistry.writer
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com" --role roles/run.developer
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA@$PROJECT_ID.iam.gserviceaccount.com" --member "serviceAccount:$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com" --role roles/iam.serviceAccountUser

POOL="github-actions"
PROVIDER="github"
gcloud iam workload-identity-pools describe "$POOL" --location global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create "$POOL" --location global --display-name "GitHub Actions"
gcloud iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool "$POOL" --location global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location global --workload-identity-pool "$POOL" --issuer-uri https://token.actions.githubusercontent.com --attribute-condition "assertion.repository=='$GITHUB_REPOSITORY'" --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com" --role roles/iam.workloadIdentityUser --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$GITHUB_REPOSITORY"
echo "WIF_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER"
echo "DEPLOY_SERVICE_ACCOUNT=$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com"
