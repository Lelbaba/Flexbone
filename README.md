# Flexbone OCR API

A stateless FastAPI service that validates JPEG uploads and sends their original bytes to Google Cloud Vision `DOCUMENT_TEXT_DETECTION`. Uploads and OCR text are never retained or logged.

## API

Run locally with Application Default Credentials:

```bash
gcloud auth application-default login
uv sync --frozen
uv run uvicorn ocr_service.app:app --reload
```

Extract text (maximum image size: exactly 10 MiB):

```bash
curl -F 'image=@sample.jpg;type=image/jpeg' http://localhost:8000/extract-text
```

Success returns `{"success":true,"text":"...","confidence":0.95,"processing_time_ms":123}`. A readable JPEG containing no text is also successful, with empty text and zero confidence. `/health` is the public liveness check and never calls Vision; `/healthz` remains a local alias because Cloud Run reserves paths ending in `z`. Interactive OpenAPI documentation is at `/docs`.

Errors always use `{"success":false,"error":{"code":"...","message":"..."},"processing_time_ms":3}`:

| Status | Codes | Meaning |
|---|---|---|
| 400 | `malformed_request`, `empty_upload` | Missing/bad multipart data or empty file |
| 413 | `image_too_large`, `request_too_large` | File/body exceeds its bound |
| 415 | `unsupported_image_format` | Decoded input is not JPEG |
| 422 | `corrupt_image` | Unreadable JPEG |
| 503 | `ocr_unavailable` | Vision unavailable or quota exhausted |
| 504 | `ocr_deadline_exceeded` | Vision deadline exhausted after retries |
| 500 | `internal_error` | Sanitized unexpected failure |

## Quality and container

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
docker build -t flexbone-ocr .
docker run --rm -p 8080:8080 -e GOOGLE_APPLICATION_CREDENTIALS=/adc.json -v "$HOME/.config/gcloud/application_default_credentials.json:/adc.json:ro" flexbone-ocr
curl http://localhost:8080/health
```

The multi-stage image runs as a non-root user, uses one Uvicorn worker, honors `$PORT`, and constructs one async Vision client per process. The application uses API, application-service, domain port, validation, and infrastructure-adapter layers. Confidence is a symbol-count-weighted mean of available word confidences.

## Google Cloud deployment

Create a billing-enabled project and budget alert first. Then run:

```bash
PROJECT_ID=my-project GITHUB_REPOSITORY=owner/repo bash scripts/bootstrap-gcp.sh
```

The bootstrap enables the required APIs, creates Artifact Registry, separate runtime/deployer identities, and repository-constrained keyless GitHub WIF. Add its two printed values and `GCP_PROJECT_ID`/`GCP_REGION` (`asia-south1`) as GitHub environment variables. The manual production workflow accepts only `main`, pushes a commit-SHA image, deploys with concurrency 8 and max 5 instances, and runs a public health check. Cloud Run retains earlier revisions; roll back with:

```bash
gcloud run services update-traffic flexbone-ocr --region asia-south1 --to-revisions REVISION=100
```

Production: **https://flexbone-ocr-dobv35r4bq-el.a.run.app**

```bash
curl https://flexbone-ocr-dobv35r4bq-el.a.run.app/health
curl -F 'image=@samples/normal.jpg;type=image/jpeg' \
  https://flexbone-ocr-dobv35r4bq-el.a.run.app/extract-text
```

Troubleshooting: verify ADC and `vision.googleapis.com` for 503s; inspect structured Cloud Run logs by request ID; confirm the runtime service account has `roles/serviceusage.serviceUsageConsumer`; and verify the upload is actual JPEG data, regardless of its extension or declared MIME type.
