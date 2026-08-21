# Implementation deep dive

Flexbone OCR is one stateless web process. It accepts an image, validates it, calls Google
Vision, and returns JSON. The production code is deliberately flat: six runtime modules, one
error class, and no database, queue, cache, repository layer, DI framework, or provider class.

For cloud setup commands, see [Infrastructure setup](INFRASTRUCTURE.md).

## Overall system

![Flexbone OCR overall system architecture](assets/system-architecture.svg)

Solid arrows are the active production path. The amber dotted path is a provisioned load
balancer and Cloud Armor configuration that is not yet authoritative. Today both custom domains
use Firebase Hosting; API paths are rewritten to Cloud Run. Cloud Run calls Vision with its
dedicated runtime identity and writes safe events to Cloud Logging.

GitHub Actions uses short-lived credentials from Workload Identity Federation. It builds an
immutable commit-SHA image, stores it in Artifact Registry, deploys a Cloud Run revision, and
runs real OCR checks against that revision.

## The simplest mental model

![FastAPI OCR request lifecycle](assets/request-flow.svg)

Follow four files to understand nearly all behavior:

1. `app.py` receives HTTP requests and returns HTTP responses.
2. `processing.py` reads, validates, and coordinates images.
3. `vision.py` makes the Google Vision call.
4. `models.py` defines response shapes and public errors.

`middleware.py` protects the HTTP boundary, while `config.py` contains limits and timeouts.
That is the complete runtime design.

## Repository structure

```text
Flexbone/
├── src/ocr_service/          The six-module FastAPI application
├── tests/                    Offline tests plus opt-in real OCR tests
├── hosting/                  Static Firebase tester and API guide
├── samples/                  Small generated API fixtures
├── test-images/              English handwriting and degraded fixtures
├── scripts/                  GCP, edge, fixture, and deployment scripts
├── docs/                     Implementation and infrastructure guides
├── .github/workflows/        CI and manual production deployment
├── Dockerfile                Non-root Cloud Run container
├── firebase.json             Hosting files and Cloud Run rewrite
├── pyproject.toml            Package and quality-tool settings
└── uv.lock                   Exact dependency lock
```

### Runtime modules

| File | Responsibility |
|---|---|
| `app.py` | Creates FastAPI, owns the Vision client lifecycle, defines routes, maps errors, and writes completion logs. |
| `processing.py` | Reads uploads, uses Pillow to verify images, applies limits/timeouts, normalizes text, and coordinates single or batch OCR. |
| `vision.py` | Sends `DOCUMENT_TEXT_DETECTION`, retries transient failures, extracts text, and calculates confidence. |
| `models.py` | Holds Pydantic response models, two small internal data records, the error table, and the single `AppError` class. |
| `middleware.py` | Rejects oversized request bodies early, creates request IDs, and adds timing headers. |
| `config.py` | Reads typed `OCR_` environment variables and computes request-body limits. |

There is intentionally no separate domain, service, validation, or adapter package. Those layers
would mostly forward calls in a project this size. Validation and orchestration live together in
`processing.py`, and the only external operation is the plainly named `vision.extract_text()`.

## Why there are still a few classes

The remaining classes are required by a library or are simple data shapes:

- FastAPI/Pydantic response classes generate and enforce the JSON contract.
- `Settings` is a Pydantic Settings model for typed environment configuration.
- `ImageMetadata` and `ValidatedImage` are immutable records that keep bytes and decoded facts
  together.
- `AppError` carries one error code. Status and safe message are looked up in one `ERRORS` table.
- The two middleware classes are required by the ASGI middleware calling convention.

There are no business-service classes. Tests inject one async OCR function into `create_app()`;
production supplies the Google Vision function with its client and settings already attached.
This is the smallest dependency seam needed to test the API without cloud credentials.

## Single-image request

1. `RequestContextMiddleware` records the start time and either accepts a bounded client request
   ID or creates a UUID.
2. `RequestBodyLimitMiddleware` checks `Content-Length` and also counts streamed ASGI chunks.
   A chunked request therefore cannot evade the body limit.
3. FastAPI parses multipart data. The route requires exactly one `image` field.
4. `read_image()` reads 64 KiB chunks and stops on the first byte beyond 10 MiB.
5. `inspect_image()` runs in a worker thread so Pillow cannot block the async event loop. It
   detects the decoded format, rejects excessive pixel dimensions, captures safe metadata, and
   calls `verify()` to catch corruption.
6. The original bytes go unchanged to `vision.extract_text()`. The application never
   recompresses or stores them.
7. The result is mapped to `SuccessResponse`; optional normalization and metadata are separate
   fields, so raw OCR text is preserved.
8. The route logs safe operational fields and middleware adds `X-Request-ID` and `Server-Timing`.

The entire single request has a 50-second application timeout, shorter than Cloud Run's
60-second timeout. This leaves time to return the documented `504` envelope.

## Batch request

A batch contains one to five repeated `images` fields. Each image is still limited to 10 MiB,
and validated image data is limited to 25 MiB for the whole request.

Validation happens independently, so a corrupt item does not discard valid items. Valid images
run behind `asyncio.Semaphore(2)`, which permits only two simultaneous Vision calls from one
batch. Results are written into their original positions and remain ordered even if later calls
finish first. A 50-second deadline covers validation and OCR; unfinished items become per-item
`504` results. A structurally valid batch returns HTTP `200`, and each item reports its own
`success` and `status_code`.

## Vision behavior

The code uses `DOCUMENT_TEXT_DETECTION` because it is designed for document-style OCR and
returns the page/block/paragraph/word/symbol hierarchy needed for confidence calculation. One
`ImageAnnotatorAsyncClient` is created during FastAPI lifespan and reused by every request in the
process.

One initial request may be followed by two retries. Deadline, service-unavailable, and internal
server failures are transient. Retries use short exponential backoff plus jitter. Quota,
authentication, and invalid-request failures are returned immediately because retrying them in
the same request would not fix them. Google exception details are never sent to clients.

Confidence is the symbol-count-weighted mean of available word confidences:

```text
confidence = Σ(word confidence × number of symbols) / Σ(number of symbols)
```

The result is clamped to 0–1. No detected text returns an empty string and `0.0` confidence.

## Error handling

All expected failures use `AppError("error_code")`. `models.ERRORS` is the single place that
maps each code to its HTTP status and public message. A FastAPI handler converts it to:

```json
{
  "success": false,
  "error": {"code": "corrupt_image", "message": "The image is corrupt or unreadable."},
  "processing_time_ms": 3
}
```

FastAPI validation errors, unknown routes, wrong HTTP methods, and unexpected exceptions also
go through the same envelope. Unexpected stack traces stay in server logs, while the response
uses `internal_error`.

## Security, privacy, and resource limits

- Uploaded bytes and OCR text are never logged or retained.
- Filenames, MIME types, extensions, EXIF, GPS, and camera data are not trusted or exposed.
- Both request transport size and decoded pixel count are bounded.
- Upload handles close on success, validation failure, batch rejection, and timeout.
- Cloud Run uses a dedicated runtime account rather than the default compute identity.
- GitHub deployment uses OIDC/WIF; no service-account JSON key exists in the repository.
- Cloud Run concurrency 8 and maximum 5 instances bound resource use and cost growth.

Starlette may spool a multipart upload to an operating-system temporary file while parsing it.
Application code creates no persistent file and keeps no reference after the request.

## Why these tools were chosen

| Tool | Reason | Cost or tradeoff |
|---|---|---|
| Python 3.12 | Clear async code, strong typing, mature Google SDK and image libraries. | Image work must be moved off the event loop. |
| FastAPI + Uvicorn | Compact ASGI API, response validation, lifespan management, and OpenAPI. | Multipart/body protection still needs explicit middleware. |
| Google Cloud Vision | Managed rotation, handwriting, and degraded-image OCR without shipping a model. | Network latency, quotas, cost, and vendor dependency. |
| Pillow | Validates decoded content instead of trusting file names or MIME types. | Untrusted decoding requires byte and pixel limits. |
| Pydantic Settings | One typed source for environment configuration and response schemas. | Adds model serialization overhead. |
| `uv` + `uv.lock` | Fast, reproducible installs locally, in CI, and in Docker. | Contributors must install `uv`. |
| Ruff + strict mypy | Fast formatting/linting plus static type checks. | Type overrides are needed for a few third-party APIs. |
| pytest + HTTPX | Tests async functions and complete HTTP behavior with a tiny fake OCR function. | Offline tests cannot prove OCR quality. |
| Docker | Gives Cloud Run the same reproducible non-root artifact tested in CI. | Adds a build step and image maintenance. |
| Cloud Run | Managed HTTPS, scale-to-zero, instance limits, identities, and revision rollback. | Cold starts and no durable local state. |
| GitHub Actions + WIF | Clean builds and keyless short-lived deployment credentials. | Initial IAM/OIDC setup is more involved. |
| Firebase Hosting | Simple static hosting, managed TLS, custom domain, and no frontend build tool. | Current API rewrite bypasses the staged Armor edge. |

## Testing

The offline suite passes an async fake function to `create_app(ocr=...)`. It covers the response
contract, status codes, multipart edge cases, exact size boundaries, decoded formats,
corruption, timeouts, batch ordering/concurrency, confidence math, and retry classification.
CI requires Ruff, strict mypy, at least 85% application coverage, and a Docker build.

The opt-in integration suite calls a real deployed revision and checks clean, rotated,
low-contrast, handwritten, blurred, 17-degree rotated, blank, and unsupported fixtures. The
manual production workflow runs it after deployment:

```bash
OCR_INTEGRATION_BASE_URL=https://your-service-url \
  uv run pytest tests/test_integration.py -m integration --no-cov
```

## Known limitations

- The API is public and unauthenticated. It has no user accounts or per-customer quotas.
- Cloud Armor rate rules are provisioned in preview but not enforced on the active path.
- There is no cache, so identical images cause another Vision request.
- Batch processing is synchronous and capped at five images and 25 MiB combined.
- GIF OCR uses only the first frame.
- Deskewing, denoising, contrast enhancement, and orientation handling are delegated to Vision.
- OCR text and confidence are model estimates, not correctness guarantees.
- Cloud Run scale-to-zero can add cold-start latency.
- The 512 MiB instance size should be load-tested if batch traffic becomes frequent.

The service should stay flat unless a real feature forces a new boundary. For example,
persistence would justify a storage module, and a second OCR engine would justify a provider
interface. Neither abstraction exists pre-emptively.
