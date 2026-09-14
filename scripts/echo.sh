#!/bin/bash
set -e

# Parse arguments
LINES=()
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --lines) LINES+=("$2"); shift ;;
    esac
    shift
done

# Print out each line
for line in "${LINES[@]}"; do
    echo "$line"
done
