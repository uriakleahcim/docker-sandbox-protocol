#!/usr/bin/env python3
import json
import os
import subprocess
import sys

# ==============================================================================
# Script: compile_policy.py
# Location: tools/compile_policy.py
#
# Description:
# Compiles the JSON permissions policy ('containers_permissions.json')
# into native Linux POSIX Access Control Lists (ACLs).
# ==============================================================================

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_DIR = os.path.join(REPO_ROOT, "config")

DEFAULT_POLICY = os.path.join(CONFIG_DIR, "containers_permissions.json")
EXAMPLE_POLICY = os.path.join(CONFIG_DIR, "containers_permissions.example.json")

POLICY_FILE = os.environ.get("SANDBOX_POLICY_FILE")
if not POLICY_FILE or not os.path.exists(POLICY_FILE):
    if os.path.exists(DEFAULT_POLICY):
        POLICY_FILE = DEFAULT_POLICY
    elif os.path.exists(EXAMPLE_POLICY):
        POLICY_FILE = EXAMPLE_POLICY
    else:
        print(f"❌ Error: Policy file not found in {CONFIG_DIR}.")
        sys.exit(1)

if os.geteuid() != 0:
    print("❌ Error: This script must be run as root or with sudo.")
    print("Please run: sudo ./compile_policy.py")
    sys.exit(1)

try:
    with open(POLICY_FILE, "r") as f:
        policy = json.load(f)
except Exception as e:
    print(f"❌ Error parsing JSON policy: {e}")
    sys.exit(1)

user = policy.get("user", "agent")
host_user = os.environ.get("SUDO_USER") or os.environ.get("USER", "root")
host_home = os.path.expanduser(f"~{host_user}")

print(f"🛡️  Compiling JSON permission policy from '{os.path.basename(POLICY_FILE)}' for user '{user}'...")

for rule in policy.get("rules", []):
    raw_path = rule.get("path", "")
    
    # Expand ~ with host_home
    expanded_path = raw_path.replace("~", host_home)
    path = expanded_path.replace("/**", "").replace("/*", "")
    
    if not path:
        continue
        
    if not os.path.exists(path):
        print(f"⚠️  Path '{path}' does not exist. Creating directory...")
        os.makedirs(path, exist_ok=True)
        try:
            import shutil
            shutil.chown(path, user=host_user, group=host_user)
        except Exception:
            pass

    perms = rule.get("permissions", [])
    
    r = "r" if "read" in perms or "list" in perms else "-"
    w = "w" if any(p in perms for p in ["write", "create", "delete"]) else "-"
    x = "x" if "execute" in perms or "list" in perms else "-"
    acl_str = f"{r}{w}{x}"
    
    if not perms:
        print(f"🚫 Completely blocking access to: {path}")
        subprocess.run(["setfacl", "-b", path], stderr=subprocess.DEVNULL)
        subprocess.run(["setfacl", "-x", f"u:{user}", path], stderr=subprocess.DEVNULL)
        continue

    print(f"⚡ Translating rule ➡️ setfacl -m u:{user}:{acl_str} {path}")
    
    if path == host_home:
        subprocess.run(["setfacl", "-m", f"u:{user}:{acl_str}", path])
    else:
        subprocess.run(["setfacl", "-b", path], stderr=subprocess.DEVNULL)
        subprocess.run(["setfacl", "-R", "-m", f"u:{user}:{acl_str}", path])
        subprocess.run(["setfacl", "-R", "-d", "-m", f"u:{user}:{acl_str}", path])

print("✅ Success! Custom JSON policy successfully compiled and active at kernel-level.")
