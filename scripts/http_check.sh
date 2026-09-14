#!/bin/bash
set -e

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --url) CHECK_URL="$2"; shift ;;
        --expect-status) EXPECTED_STATUS="$2"; shift ;;
        --timeout-seconds) TIMEOUT_SECONDS="$2"; shift ;;
    esac
    shift
done

if [ -z "$CHECK_URL" ]; then
    echo "ERROR: --url is required" >&2
    exit 1
fi

EXPECTED_STATUS="${EXPECTED_STATUS:-200}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-10}"

echo "Performing HTTP check for url: $CHECK_URL (expecting status: $EXPECTED_STATUS, timeout: ${TIMEOUT_SECONDS}s)"

# Run curl to get the status code
STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT_SECONDS" "$CHECK_URL" || true)

if [ "$STATUS_CODE" = "000" ] || [ -z "$STATUS_CODE" ]; then
    echo "ERROR: Connection failed or timed out for url '$CHECK_URL'." >&2
    exit 1
fi

if [ "$STATUS_CODE" -ne "$EXPECTED_STATUS" ]; then
    echo "ERROR: Expected HTTP status $EXPECTED_STATUS, but got $STATUS_CODE for url '$CHECK_URL'." >&2
    exit 1
fi

echo "HTTP check successful: Got status $STATUS_CODE as expected."
