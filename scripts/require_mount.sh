#!/bin/bash
set -e

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --path) MOUNT_PATH="$2"; shift ;;
        --must_be_writable) MUST_BE_WRITABLE="$2"; shift ;;
    esac
    shift
done

if [ -z "$MOUNT_PATH" ]; then
    echo "ERROR: --path is required" >&2
    exit 1
fi

echo "Verifying require_mount for path: $MOUNT_PATH"

if [ ! -d "$MOUNT_PATH" ]; then
    echo "ERROR: Directory '$MOUNT_PATH' does not exist." >&2
    exit 1
fi

# Check if mountpoint or fallback to /proc/mounts / /proc/self/mountinfo
IS_MOUNT=0
if command -v mountpoint &> /dev/null; then
    if mountpoint -q "$MOUNT_PATH"; then
        IS_MOUNT=1
    fi
else
    # Normalize path to remove trailing slash
    NORM_PATH="${MOUNT_PATH%/}"
    if grep -q " $NORM_PATH " /proc/mounts; then
        IS_MOUNT=1
    fi
fi

if [ "$IS_MOUNT" -ne 1 ]; then
    echo "Path '$MOUNT_PATH' is not currently mounted. Attempting to mount..."
    if sudo mount "$MOUNT_PATH"; then
        echo "Successfully mounted $MOUNT_PATH."
        IS_MOUNT=1
    else
        echo "ERROR: Path '$MOUNT_PATH' is not a mount point and mounting failed." >&2
        exit 1
    fi
fi

# Check if writable if required
if [ "$MUST_BE_WRITABLE" = "true" ]; then
    TMP_FILE="$MOUNT_PATH/.mount_write_test_$$"
    if ! touch "$TMP_FILE" &> /dev/null; then
        echo "ERROR: Mount point '$MOUNT_PATH' is read-only or not writable." >&2
        exit 1
    fi
    rm -f "$TMP_FILE"
fi

echo "Mount point verification successful for: $MOUNT_PATH"
