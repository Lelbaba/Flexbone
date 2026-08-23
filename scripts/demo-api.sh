#!/usr/bin/env bash
# Flexbone OCR API demonstration.
#
#   bash scripts/demo-api.sh                       # against production
#   BASE_URL=http://localhost:8000 DELAY=0 \
#     bash scripts/demo-api.sh                     # against a local server
#
# Production enforces per-IP Cloud Armor limits of ten single-image and two batch
# requests per minute, so this script paces itself. Set DELAY=0 only when the
# target is a local server with no edge in front of it.
set -uo pipefail
cd "$(dirname "$0")/.."

BASE_URL="${BASE_URL:-https://api.ocr.lelbaba.top}"
DELAY="${DELAY:-8}"
BATCH_DELAY="${BATCH_DELAY:-40}"

pretty() { python3 -m json.tool --no-ensure-ascii 2>/dev/null || cat; }

# Echo an argument list the way a person would type it.
shq() {
  local a
  for a in "$@"; do
    if [[ "$a" =~ ^[A-Za-z0-9_./:@=-]+$ ]]; then printf ' %s' "$a"
    else printf " '%s'" "${a//\'/\'\\\'\'}"; fi
  done
}

case_n=0
run() {           # run <title> <curl args...>
  local title="$1"; shift
  case_n=$((case_n + 1))
  printf '\n═══ Case %d — %s\n\n' "$case_n" "$title"
  printf '$ curl'; shq "$@"; printf '\n\n'
  local out status body
  out="$(curl -sS -w $'\n%{http_code}' "$@")"
  status="${out##*$'\n'}"
  body="${out%$'\n'*}"
  printf 'HTTP %s\n' "$status"
  printf '%s\n' "$body" | pretty
}

printf '### Flexbone OCR API demo — %s\n' "$BASE_URL"

# ---------------------------------------------------------------- health
run "Health check (not rate limited)" -X GET "$BASE_URL/health"

# ------------------------------------------------- single-image endpoint
run "Single image, clean printed text" \
  -X POST -F 'image=@samples/normal.jpg;type=image/jpeg' "$BASE_URL/extract-text"
sleep "$DELAY"

run "Single image with metadata and normalized text" \
  -X POST -F 'image=@test-images/english-eye-chart.jpg;type=image/jpeg' \
  "$BASE_URL/extract-text?metadata=true&normalize=true"
sleep "$DELAY"

run "Rotated image (Vision handles orientation)" \
  -X POST -F 'image=@samples/rotated.jpg;type=image/jpeg' \
  "$BASE_URL/extract-text?metadata=true"
sleep "$DELAY"

run "Handwriting" \
  -X POST -F 'image=@test-images/english-handwriting.jpg;type=image/jpeg' \
  "$BASE_URL/extract-text?normalize=true"
sleep "$DELAY"

run "Image with no text — success, empty text, zero confidence" \
  -X POST -F 'image=@samples/blank.jpg;type=image/jpeg' "$BASE_URL/extract-text"
sleep "$DELAY"

run "Unsupported format — 415" \
  -X POST -F 'image=@samples/unsupported.bmp;type=image/bmp' "$BASE_URL/extract-text"
sleep "$DELAY"

run "Corrupt file — 422 (content is checked, not the extension)" \
  -X POST -F 'image=@samples/corrupt.jpg;type=image/jpeg' "$BASE_URL/extract-text"
sleep "$DELAY"

run "Missing image field — 400" -X POST "$BASE_URL/extract-text"
sleep "$DELAY"

# -------------------------------------------------------- batch endpoint
run "Batch of three images, with metadata and normalized text" \
  -X POST \
  -F 'images=@samples/normal.jpg;type=image/jpeg' \
  -F 'images=@samples/rotated.jpg;type=image/jpeg' \
  -F 'images=@samples/supported.png;type=image/png' \
  "$BASE_URL/extract-text/batch?metadata=true&normalize=true"
sleep "$BATCH_DELAY"

run "Mixed batch — one item failing does not discard the others" \
  -X POST \
  -F 'images=@samples/normal.jpg;type=image/jpeg' \
  -F 'images=@samples/corrupt.jpg;type=image/jpeg' \
  -F 'images=@samples/unsupported.bmp;type=image/bmp' \
  "$BASE_URL/extract-text/batch"

printf '\n### Done — %d cases\n' "$case_n"
