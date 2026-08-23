#!/usr/bin/env bash
# Demonstrate the deployed API's single-image Cloud Armor rate limit.
#
# Wait at least 60 seconds after any previous /extract-text requests, then run:
#   bash scripts/test-rate-limit.sh
#
# This uploads a real image 15 times. The first 10 requests should complete OCR
# with HTTP 200; the remaining 5 should be rejected at the edge with HTTP 429.
# Unlike the old bodyless-request test, this uses Google Vision quota.
set -uo pipefail

BASE_URL="${BASE_URL:-https://api.ocr.lelbaba.top}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_FILE="${IMAGE_FILE:-$SCRIPT_DIR/../samples/normal.jpg}"
REQUEST_COUNT=15
EXPECTED_SUCCEEDED=10
EXPECTED_THROTTLED=5

if [ ! -f "$IMAGE_FILE" ]; then
  printf 'Image not found: %s\n' "$IMAGE_FILE" >&2
  exit 1
fi

BODY_FILE="$(mktemp)"
HEADER_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE" "$HEADER_FILE"' EXIT

succeeded=0
throttled=0
unexpected=0

printf 'Sending %d valid OCR requests to %s/extract-text\n' \
  "$REQUEST_COUNT" "$BASE_URL"
printf 'Expected: %d succeed (200), then %d are rate-limited (429)\n\n' \
  "$EXPECTED_SUCCEEDED" "$EXPECTED_THROTTLED"

for request_number in $(seq 1 "$REQUEST_COUNT"); do
  code="$(curl -sS \
    -D "$HEADER_FILE" \
    -o "$BODY_FILE" \
    -w '%{http_code}' \
    -F "image=@${IMAGE_FILE}" \
    "$BASE_URL/extract-text")"

  case "$code" in
    200)
      result="succeeded"
      succeeded=$((succeeded + 1))
      ;;
    429)
      result="rate limited"
      throttled=$((throttled + 1))
      ;;
    *)
      result="unexpected"
      unexpected=$((unexpected + 1))
      ;;
  esac

  printf '  request %2d: %s (%s)\n' "$request_number" "$code" "$result"
done

printf '\nSummary: %d succeeded, %d rate limited, %d unexpected\n' \
  "$succeeded" "$throttled" "$unexpected"

if [ "$succeeded" -eq "$EXPECTED_SUCCEEDED" ] && \
   [ "$throttled" -eq "$EXPECTED_THROTTLED" ] && \
   [ "$unexpected" -eq 0 ]; then
  printf 'PASS: 10 requests went through and succeeded; 5 were blocked.\n'
  exit 0
fi

printf 'FAIL: expected exactly 10 HTTP 200 responses and 5 HTTP 429 responses.\n' >&2
printf 'Wait at least 60 seconds for the per-IP window to reset, then retry.\n' >&2
exit 1
