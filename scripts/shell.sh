#!/bin/bash
set -e

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --command) EXEC_COMMAND="$2"; shift ;;
        --timeout-seconds) TIMEOUT_SECONDS="$2"; shift ;;
        --container) CONTAINER_NAME="$2"; shift ;;
    esac
    shift
done

if [ -z "$EXEC_COMMAND" ]; then
    echo "ERROR: --command is required" >&2
    exit 1
fi

if [ -z "$CONTAINER_NAME" ]; then
    echo "ERROR: --container is required" >&2
    exit 1
fi

echo "Running shell command in container '$CONTAINER_NAME'..."

# Prepare the command execution with timeout if specified
TIMEOUT_PREFIX=""
if [ -n "$TIMEOUT_SECONDS" ] && [ "$TIMEOUT_SECONDS" -gt 0 ]; then
    TIMEOUT_PREFIX="timeout $TIMEOUT_SECONDS"
fi

# Run the command inside the container via docker exec
if [ -n "$TIMEOUT_PREFIX" ]; then
    docker exec "$CONTAINER_NAME" sh -c "$TIMEOUT_PREFIX sh -c \"$EXEC_COMMAND\""
else
    docker exec "$CONTAINER_NAME" sh -c "$EXEC_COMMAND"
fi
