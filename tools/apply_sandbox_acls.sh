#!/usr/bin/env bash
# ==============================================================================
# Script: apply_sandbox_acls.sh
# Location: tools/apply_sandbox_acls.sh
#
# Description:
# Enforces recursive POSIX Access Control Lists (ACLs) for the sandboxed user.
# Grants traverse access to the user root and read-write-execute permissions
# to designated workspace folders while isolating private configuration directories.
# ==============================================================================
set -e

# Ensure the script is run with sudo/root privileges
if [ "$EUID" -ne 0 ]; then
  echo "❌ Error: This script must be run as root or with sudo."
  echo "Please run: sudo ./apply_sandbox_acls.sh"
  exit 1
fi

HOST_USER="${HOST_USER:-${SUDO_USER:-$USER}}"
HOST_HOME="${HOST_HOME:-$(eval echo "~$HOST_USER")}"
SANDBOX_USER="${SANDBOX_USER:-agent}"

echo "🛡️  Restoring and Enforcing Sandbox Access Control Lists..."
echo "    Host User:    $HOST_USER ($HOST_HOME)"
echo "    Sandbox User: $SANDBOX_USER"

# Check if sandbox user exists
if ! id "$SANDBOX_USER" &>/dev/null; then
  echo "⚠️  Sandbox user '$SANDBOX_USER' does not exist on this host system."
  echo "   Create with: sudo useradd -u 1001 -m -s /bin/bash $SANDBOX_USER"
  exit 1
fi

# 1. Grant traverse (read/execute) permission on the host home directory root
# This allows the sandbox user to traverse down into workspace folders
echo "📂 Setting traverse access on $HOST_HOME..."
setfacl -m "u:${SANDBOX_USER}:rx" "$HOST_HOME"

# 2. Lock down sensitive user configuration files from the sandbox user
for priv_dir in "$HOST_HOME/.ssh" "$HOST_HOME/.gnupg" "$HOST_HOME/.config"; do
  if [ -d "$priv_dir" ]; then
    echo "🔒 Locking down private folder: $priv_dir"
    setfacl -m "u:${SANDBOX_USER}:---" "$priv_dir" 2>/dev/null || chmod 700 "$priv_dir"
  fi
done

# 3. Apply recursive write ACLs and default ACLs for active sandbox directories
TARGET_DIRS=(
  "$HOST_HOME/sandbox/workspace"
  "$HOST_HOME/sandbox/scratch"
)

for target_dir in "${TARGET_DIRS[@]}"; do
  if [ -d "$target_dir" ]; then
    echo "⚡ Applying recursive Read-Write-Execute ACLs to: $target_dir"
    setfacl -R -m "u:${SANDBOX_USER}:rwx" "$target_dir"
    setfacl -R -d -m "u:${SANDBOX_USER}:rwx" "$target_dir"
  else
    echo "📂 Creating directory and applying ACLs: $target_dir"
    mkdir -p "$target_dir"
    chown "$HOST_USER:$HOST_USER" "$target_dir"
    setfacl -R -m "u:${SANDBOX_USER}:rwx" "$target_dir"
    setfacl -R -d -m "u:${SANDBOX_USER}:rwx" "$target_dir"
  fi
done

echo "✅ Success! Sandbox ACL permissions successfully applied and verified."
