#!/bin/bash
set -e

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --path) DIR_PATH="$2"; shift ;;
        --mode) DIR_MODE="$2"; shift ;;
        --owner) DIR_OWNER="$2"; shift ;;
        --group) DIR_GROUP="$2"; shift ;;
    esac
    shift
done

if [ -z "$DIR_PATH" ]; then
    echo "ERROR: --path is required" >&2
    exit 1
fi

echo "Running ensure_dir for path: $DIR_PATH"

# Create directory if not exists
if [ ! -d "$DIR_PATH" ]; then
    mkdir -p "$DIR_PATH"
fi

# Apply owner/group and permissions
if [ -n "$DIR_MODE" ]; then
    chmod "$DIR_MODE" "$DIR_PATH"
fi

if [ -n "$DIR_OWNER" ]; then
    chown "$DIR_OWNER" "$DIR_PATH"
fi

if [ -n "$DIR_GROUP" ]; then
    chgrp "$DIR_GROUP" "$DIR_PATH"
fi

echo "Directory $DIR_PATH is prepared successfully."
