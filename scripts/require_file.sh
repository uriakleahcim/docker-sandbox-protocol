#!/bin/bash
set -e

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --path) FILE_PATH="$2"; shift ;;
    esac
    shift
done

if [ -z "$FILE_PATH" ]; then
    echo "ERROR: --path is required" >&2
    exit 1
fi

echo "Verifying require_file for path: $FILE_PATH"

if [ ! -f "$FILE_PATH" ]; then
    echo "ERROR: Required file '$FILE_PATH' does not exist." >&2
    exit 1
fi

echo "Required file exists: $FILE_PATH"
