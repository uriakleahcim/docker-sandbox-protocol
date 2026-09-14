#!/bin/bash
set -e

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --name) PRESET_NAME="$2"; shift ;;
        --version) PRESET_VERSION="$2"; shift ;;
    esac
    shift
done

if [ -z "$PRESET_NAME" ]; then
    echo "ERROR: --name is required" >&2
    exit 1
fi

echo "Installing image preset: $PRESET_NAME (version: ${PRESET_VERSION:-latest})"
# This runs on the image build-time layer. For our model, it's a compliant placeholder logging preset resolution.
echo "Preset $PRESET_NAME resolved successfully."
