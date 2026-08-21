# Flexbone OCR API

A stateless FastAPI service that validates image uploads and sends their original bytes to Google Cloud Vision `DOCUMENT_TEXT_DETECTION`. It supports single and batch OCR, optional safe metadata, and opt-in text normalization. Uploads and OCR results are never retained or logged.

## Live services

| Resource | URL |
|---|---|
| Browser tester | <https://ocr.lelbaba.top> |
| API | <https://api.ocr.lelbaba.top> |
| Direct Cloud Run service | <https://flexbone-ocr-dobv35r4bq-el.a.run.app> |
| API guide | <https://api.ocr.lelbaba.top/docs> |
| OpenAPI schema | <https://api.ocr.lelbaba.top/openapi.json> |
| Health check | <https://api.ocr.lelbaba.top/health> |

The API currently reaches Cloud Run through a Firebase Hosting rewrite. A global external Application Load Balancer and Cloud Armor policy are provisioned with rate-limit rules in preview, but the final API DNS and ingress cutover has not yet been applied. See [Infrastructure setup](docs/INFRASTRUCTURE.md) for the exact topology and cutover procedure.

## Requirements

- Git
- Python 3.12
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- A billing-enabled Google Cloud project with the Vision API enabled
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
- Docker, only for container build and smoke testing

Firebase CLI, GitHub CLI, `jq`, and a domain are additionally required for a full cloud deployment.

## Local setup

Clone the repository and install the locked runtime and development dependencies:

```bash
git clone git@github.com:Lelbaba/Flexbone.git
cd Flexbone
uv sync --frozen
```

Authenticate Application Default Credentials and assign Vision requests to your billing-enabled project:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
gcloud services enable vision.googleapis.com --project YOUR_PROJECT_ID
```

Start the API:

```bash
uv run uvicorn ocr_service.app:app --reload
```

Verify it from another terminal:

```bash
curl http://localhost:8000/health
curl -F 'image=@samples/normal.jpg;type=image/jpeg' \
  http://localhost:8000/extract-text
```

The application reads configuration from `OCR_`-prefixed environment variables:

| Variable | Default | Purpose |
|---|---:|---|
| `OCR_MAX_IMAGE_BYTES` | `10485760` | Maximum bytes per image |
| `OCR_MAX_IMAGE_PIXELS` | `40000000` | Maximum decoded width × height |
| `OCR_MAX_BATCH_IMAGES` | `5` | Images accepted by one batch |
| `OCR_MAX_BATCH_IMAGE_BYTES` | `26214400` | Maximum combined image bytes |
| `OCR_BATCH_MAX_CONCURRENCY` | `2` | Concurrent Vision calls per batch |
| `OCR_BATCH_TIMEOUT_SECONDS` | `50` | Whole-batch processing budget |
| `OCR_REQUEST_TIMEOUT_SECONDS` | `50` | Whole single-image request budget |
| `OCR_VISION_TIMEOUT_SECONDS` | `20` | Deadline for each Vision attempt |
| `OCR_VISION_MAX_RETRIES` | `2` | Retries after the initial attempt |
| `OCR_PUBLIC_DOCS_URL` | `https://ocr.lelbaba.top/api-docs.html` | Target of `/docs` |

## API examples

Single image, with optional metadata and normalized text:

```bash
curl -F 'image=@samples/normal.jpg;type=image/jpeg' \
  'http://localhost:8000/extract-text?metadata=true&normalize=true'
```

Batch OCR uses repeated `images` fields. It accepts one to five images, up to 10 MiB each and 25 MiB combined, and runs at most two Vision calls simultaneously:

```bash
curl \
  -F 'images=@samples/normal.jpg;type=image/jpeg' \
  -F 'images=@samples/rotated.jpg;type=image/jpeg' \
  -F 'images=@samples/supported.png;type=image/png' \
  'http://localhost:8000/extract-text/batch?metadata=true&normalize=true'
```

JPEG, PNG, and GIF are supported; only the first frame of an animated GIF is processed. File contents are decoded and verified instead of trusting the extension or client MIME type. Exact request, response, and error contracts are in the [API guide](https://ocr.lelbaba.top/api-docs.html).

## Quality checks

The ordinary test suite injects a fake OCR function and does not need Google credentials:

```bash
uv sync --frozen
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

The configured coverage gate is 85%. API, validation, batch concurrency, confidence aggregation, provider failure, retry, and error-contract behavior are covered.

To verify the deployed service against real Vision with normal, rotated, low-contrast,
handwritten, degraded, and blank fixtures:

```bash
OCR_INTEGRATION_BASE_URL=https://your-service-url \
  uv run pytest tests/test_integration.py -m integration --no-cov
```

The production workflow runs this suite against the new Cloud Run revision after every
manual deployment.

## Container

Build and run the same non-root image used by Cloud Run:

```bash
docker build -t flexbone-ocr .
docker run --rm -p 8080:8080 \
  -e GOOGLE_APPLICATION_CREDENTIALS=/adc.json \
  -v "$HOME/.config/gcloud/application_default_credentials.json:/adc.json:ro" \
  flexbone-ocr
curl http://localhost:8080/health
```

The image uses one Uvicorn worker, one reusable asynchronous Vision client, and Cloud Run's `$PORT` environment variable.

## Deployment

For a complete deployment—from project creation and billing through IAM, keyless GitHub Actions, Artifact Registry, Cloud Run, Firebase Hosting, custom domains, HTTPS load balancing, Cloud Armor, DNS cutover, verification, and rollback—follow [Infrastructure setup](docs/INFRASTRUCTURE.md).

The short path after prerequisites are satisfied is:

```bash
PROJECT_ID=your-project-id \
GITHUB_REPOSITORY=owner/repository \
bash scripts/bootstrap-gcp.sh
```

The script prints the two Workload Identity Federation values needed by GitHub Actions. It does not create a project, attach billing, configure a budget, modify DNS, or create Firebase Hosting; those deliberate account-level steps are documented in the infrastructure runbook.

## Documentation

- [Implementation deep dive](docs/IMPLEMENTATION.md): runtime architecture, project structure, design patterns, module responsibilities, technology choices, behavior, tradeoffs, and limitations.
- [Infrastructure setup](docs/INFRASTRUCTURE.md): reproducible, from-scratch cloud and domain deployment.
- [API guide](https://ocr.lelbaba.top/api-docs.html): public request and response contract.
- [Test images](test-images/README.md): redistribution-safe OCR fixtures and their intended use.

Because the GitHub repository is private, an evaluator also needs explicit repository access;
the public service and API documentation do not require authentication.

## Troubleshooting

- `503 ocr_unavailable`: verify ADC, project billing, `vision.googleapis.com`, runtime service-account access, and Vision quota.
- `504 ocr_deadline_exceeded`: retry later or use a clearer/smaller image; the provider deadline has been exhausted.
- `413`: check per-image, combined batch, decoded dimension, and multipart body limits.
- Local credential quota errors: rerun `gcloud auth application-default set-quota-project YOUR_PROJECT_ID`.
- Deployment authentication errors: verify the four GitHub variables and the repository constraint on the WIF provider.
- Cloud failures: search Cloud Run structured logs by `x-request-id`; image bytes and OCR text are intentionally absent from logs.

Cloud Run keeps previous revisions. Roll back traffic with:

```bash
gcloud run services update-traffic flexbone-ocr \
  --project YOUR_PROJECT_ID \
  --region asia-south1 \
  --to-revisions REVISION_NAME=100
```
