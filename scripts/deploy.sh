#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
REPOSITORY="${REPOSITORY:-flexbone}"
SERVICE="${SERVICE:-flexbone-ocr}"
TAG="${TAG:-$(git rev-parse HEAD)}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$SERVICE:$TAG"
gcloud builds submit --tag "$IMAGE"
gcloud run deploy "$SERVICE" --image "$IMAGE" --region "$REGION" \
  --service-account "ocr-runtime@$PROJECT_ID.iam.gserviceaccount.com" \
  --cpu 1 --memory 512Mi --concurrency 8 --min 0 --max 5 --timeout 60 \
  --no-invoker-iam-check
gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'

