.\" Flexbone OCR implementation explanation. Build from the repository root with:
.\" rsvg-convert -f pdf1.4 -o /tmp/flexbone-architecture.pdf docs/assets/system-architecture.svg
.\" gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 -sOutputFile=docs/assets/system-architecture.pdf /tmp/flexbone-architecture.pdf
.\" groff -U -Tpdf -ms -m pdfpic docs/FLEXBONE_IMPLEMENTATION_EXPLANATION.ms > docs/Flexbone_Implementation_Explanation.pdf
.fam H
.nr PS 10
.nr VS 14
.nr HM 0.65i
.nr FM 0.65i
.nr PO 0.72i
.nr LL 7.06i
.ds CH Flexbone OCR - Implementation Explanation
.ds CF Page \\n(PN
.hy 0
.
.sp 1.1i
.ce 1
.ps 25
.B "Flexbone OCR"
.sp 0.18i
.ce 1
.ps 17
.B "Implementation and Infrastructure Explanation"
.sp 0.2i
.ce 1
.ps 11
OCR service, upload validation, system architecture, and deployment strategy
.sp 0.75i
.ps 13
.B "Overall introduction"
.ps 10
.PP
Flexbone OCR is a small, stateless API I built to accept an image and return the text found in it. Google Cloud Vision handles the OCR, FastAPI provides the API, and Google Cloud Run hosts it. The service supports both single-image and batch requests without saving uploaded images or OCR text.
.sp 0.3i
.B "Live links"
.IP "Browser tester" 1.35i
https://ocr.lelbaba.top
.IP "API base URL" 1.35i
https://api.ocr.lelbaba.top
.IP "API documentation" 1.35i
https://api.ocr.lelbaba.top/docs
.IP "OpenAPI schema" 1.35i
https://api.ocr.lelbaba.top/openapi.json
.bp
.
.NH 1
Technology stack
.PP
The stack is intentionally simple and mostly managed. That lets me focus on safe image handling and reliable OCR instead of maintaining servers or training an OCR model. The Python API is packaged as a Docker image and deployed to Google Cloud, with automated checks verifying the code and container before release.
.sp 0.15i
.IP "Python 3.12" 1.65i
Python powers the backend because it has clear async support and mature libraries for image processing and Google Cloud.
.IP "FastAPI and Uvicorn" 1.65i
FastAPI defines the HTTP endpoints and response models. Uvicorn runs the FastAPI application inside the container.
.IP "Google Cloud Vision API" 1.65i
OCR is handled by the DOCUMENT_TEXT_DETECTION feature. It works well for document-style text, handwriting, rotated images, and degraded images without requiring me to host a model.
.IP "Pillow" 1.65i
Pillow opens and verifies the real image content, so validation does not depend on an untrusted filename, extension, or MIME type.
.IP "Pydantic Settings" 1.65i
Typed settings keep limits, timeouts, the allowed browser origin, and other configuration in one place. Environment variables use the OCR_ prefix.
.IP "Docker" 1.65i
The backend is packaged as a reproducible, non-root container. The same Dockerfile is built in CI and deployed to Cloud Run.
.IP "uv and uv.lock" 1.65i
uv installs the dependencies, while the lock file keeps local, CI, and container environments consistent.
.IP "pytest and HTTPX" 1.65i
Together, they test API behavior, validation, error responses, concurrency, retries, and integration with the deployed service.
.IP "Ruff and mypy" 1.65i
Ruff checks formatting and code quality, while strict mypy checks type safety.
.IP "GitHub Actions" 1.65i
GitHub Actions runs continuous integration and the controlled production deployment workflow.
.bp
.
.NH 1
Overall system architecture
.PP
All API traffic goes through the protected Google Cloud edge before it reaches the FastAPI container. The container validates the upload, sends the image bytes to Google Cloud Vision, and returns a JSON response. There is no other route in: the container itself refuses any request that does not arrive through the load balancer.
.sp 0.18i
.PDFPIC -C docs/assets/system-architecture.pdf 6.85i
.sp 0.1i
.ce 1
.ps 8
Flexbone OCR system architecture
.ps 10
.sp 0.18i
.PP
An API client sends an image to the API domain over HTTPS. The global HTTPS load balancer receives the request, Cloud Armor applies the per-IP rate limits, and the request reaches Cloud Run through a serverless network endpoint group. Inside the container, FastAPI validates the upload and calls Google Cloud Vision, then returns the JSON response back along the same path. Safe operational events go to Cloud Logging, but the uploaded image and the extracted text are never logged.
.bp
.
.NH 2
The FastAPI codebase
.PP
I kept the backend deliberately small, with one clear responsibility for each file. This makes the request flow easy to follow and test without adding a large framework or unnecessary abstraction.
.IP "app.py" 1.35i
This is the entry point of the API. It defines the health, single-image, and batch endpoints; starts the reusable Vision client; maps errors into one JSON format; and writes safe completion logs.
.IP "middleware.py" 1.35i
This is where the total HTTP request-body limit is enforced, including for streamed requests. It also handles request IDs and adds timing headers to every response.
.IP "processing.py" 1.35i
This module handles the main processing flow: reading bounded chunks, validating with Pillow, applying image and batch limits, controlling concurrency, enforcing deadlines, optionally normalizing text, and preserving result order.
.IP "vision.py" 1.35i
All communication with Google Cloud Vision lives here, including attempt timeouts, retries for temporary failures, text extraction, and confidence calculation.
.IP "models.py" 1.35i
This file defines the public response shapes and the safe error table. Expected failures use a small AppError code instead of exposing internal Google or Python errors.
.IP "config.py" 1.35i
All typed limits and timeouts live here, giving me one place to review or change the service's operational boundaries.
.sp 0.25i
.LP
.B "Important implementation features"
.IP "File size limits" 1.6i
Each image is limited to 10 MiB. The middleware also rejects an oversized HTTP body early, and streamed chunks are counted so a client cannot bypass the limit.
.IP "Image validation" 1.6i
The accepted formats are JPEG, PNG, and GIF. Pillow checks the decoded format, verifies the file, and rejects corruption or more than 40 million pixels. For a GIF, only the first frame is processed.
.IP "Safe upload handling" 1.6i
Each upload is read in 64 KiB chunks and stops as soon as it crosses the limit. Upload handles close on both success and failure, and the image is never saved permanently.
.bp
.
.NH 2
API features and safeguards
.IP "Single-image OCR" 1.75i
The /extract-text endpoint accepts one image and returns the raw OCR text, confidence score, processing time, and optional safe metadata or normalized text.
.IP "Batch OCR" 1.75i
The batch endpoint accepts one to five images. Each image can be 10 MiB, but validated image data is limited to 25 MiB for the full batch.
.IP "Batch concurrency" 1.75i
A batch can make at most two Vision calls at the same time. This controls provider usage and memory while preserving the original result order.
.IP "Timeouts and retries" 1.75i
A request has a 50-second application deadline, shorter than Cloud Run's 60-second limit. A Vision attempt has a 20-second deadline, and temporary failures can be retried twice.
.IP "Consistent errors" 1.75i
Validation failures, unknown routes, provider errors, timeouts, and unexpected failures use one safe JSON error structure. Internal exception details stay in logs.
.IP "Privacy" 1.75i
Image bytes, filenames, EXIF data, and OCR text are never retained or logged. Logs contain only safe operational details such as format, byte count, status, timing, and retry count.
.IP "CORS" 1.75i
The API allows browser requests from one configured origin only, and credentials are disabled because the API has no authentication. This keeps browser access narrow, while command-line and server-side API clients are unaffected.
.IP "Request IDs" 1.75i
Every response includes an X-Request-ID, which lets me connect an API report with Cloud Run logs without recording sensitive content.
.IP "Rate limiting" 1.75i
Google Cloud Armor applies per-IP rate limits at the load balancer before requests reach FastAPI: ten single-image requests and two batch requests per minute per IP address, with anything above that answered by the edge as a 429. This is an infrastructure safeguard rather than application middleware, so it keeps working even if the application is busy.
.IP "Scaling and cost limits" 1.75i
Cloud Run can scale from zero to a maximum of five instances. Each instance uses one CPU, 512 MiB of memory, and concurrency of eight.
.sp 0.3i
.PP
The main design idea is defense in depth: Cloud Armor controls request frequency, middleware controls transport size, Pillow controls decoded image safety, processing code controls concurrency and deadlines, and Vision performs the OCR.
.bp
.
.NH 2
Infrastructure components
.PP
Unless I note otherwise, every component below is a Google Cloud (GCP) service inside the same project.
.sp 0.1i
.IP "Public DNS records" 2.2i
The authoritative DNS records live at my domain registrar rather than in Cloud DNS. The API name is an A record pointing at the load balancer's global static IP address.
.IP "Certificate Manager" 2.2i
Certificate Manager issues and automatically renews the TLS certificate that the load balancer presents for the API domain.
.IP "HTTPS load balancer" 2.2i
A global external Application Load Balancer is the only public entry point for the API. It terminates HTTPS and forwards permitted traffic toward Cloud Run.
.IP "Cloud Armor" 2.2i
Cloud Armor enforces the per-IP rate limits at the edge, so unwanted traffic is rejected before it can consume application or Vision resources.
.IP "Serverless NEG" 2.2i
A serverless network endpoint group is the supported bridge from the load balancer to Cloud Run. Its backend service is what attaches Cloud Armor and request logging to the route.
.IP "Cloud Run" 2.2i
Cloud Run runs the non-root FastAPI container. It manages revisions, automatic scaling, the runtime service identity, and rollback.
.IP "Cloud Vision API" 2.2i
Vision performs DOCUMENT_TEXT_DETECTION on the validated image bytes and returns the text and per-word confidence to the backend.
.IP "Artifact Registry" 2.2i
Artifact Registry is GCP's managed container-image registry. Every production image is stored there under its immutable Git commit SHA.
.IP "IAM service accounts" 2.2i
Two separate service accounts split deployment from runtime access. The deployer can only push and release images, while the runtime identity can only reach the Google services the application actually needs.
.IP "Workload Identity Federation" 2.2i
Workload Identity Federation gives GitHub Actions short-lived Google credentials, so no permanent service-account key is ever stored in GitHub.
.IP "Cloud Logging" 2.2i
Cloud Logging collects safe events from the application, Cloud Run, the load balancer, and Cloud Armor for troubleshooting and request tracing.
.IP "GitHub Actions" 2.2i
GitHub Actions, on GitHub rather than GCP, runs the quality checks and the production workflow that builds, publishes, deploys, and verifies the backend.
.bp
.
.NH 1
CI/CD and deployment strategy
.PP
My release process combines automatic continuous integration with a controlled production release. Every push and pull request runs CI, while production deployment is started manually from the main branch through GitHub's production environment. Because I decide when to release, this is continuous delivery rather than fully automatic continuous deployment.
.sp 0.2i
.B "Continuous integration"
.IP "1." 0.35i
GitHub Actions checks out the exact commit and installs the locked dependencies with uv.
.IP "2." 0.35i
It checks the lock file, formatting, lint rules, and strict Python types.
.IP "3." 0.35i
It runs the offline pytest suite with an 85 percent application coverage requirement.
.IP "4." 0.35i
It builds the Dockerfile and confirms the application can be imported inside the production image.
.sp 0.15i
.LP
.B "Production delivery"
.IP "1." 0.35i
When I trigger the workflow on main, GitHub creates a short-lived identity token. Google verifies that it came from my repository and temporarily authorizes the deployment service account.
.IP "2." 0.35i
The workflow builds the Docker image and tags it with the Git commit SHA, so I can trace every image to one exact source revision.
.IP "3." 0.35i
It pushes that immutable image to Google Cloud Artifact Registry.
.IP "4." 0.35i
It creates a new Cloud Run revision with the protected ingress, scaling limits, timeouts, and runtime service account.
.IP "5." 0.35i
Cloud Run pulls the selected image from Artifact Registry. Public traffic continues to enter through the load balancer and Cloud Armor.
.IP "6." 0.35i
The workflow calls the public health endpoint and then runs real OCR integration tests through the production API domain.
.sp 0.2i
.LP
.B "How deployment connects to the infrastructure"
.PP
GitHub Actions is the delivery controller, Artifact Registry is the handoff point for the built image, and Cloud Run is the runtime. The load balancer and Cloud Armor remain in front of every new revision because the deployment command preserves load-balanced-only ingress and disables the direct Cloud Run URL.
.sp 0.2i
.B "Rollback"
.PP
Every deployment creates a new Cloud Run revision and keeps earlier revisions available. If a release is faulty, I can route all traffic back to a known-good revision without rebuilding it. The current workflow verifies the new release after deployment, but rollback is a deliberate operational action rather than an automatic workflow step.
