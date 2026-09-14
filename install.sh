#!/usr/bin/env bash
# ==============================================================================
# Script: install.sh
# Project: Docker Sandbox Protocol
# Description: Automated setup and installer for Linux workstations/servers.
# ==============================================================================
set -e

GREEN="\033[92m"
BLUE="\033[94m"
YELLOW="\033[93m"
RED="\033[91m"
BOLD="\033[1m"
RESET="\033[0m"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "\n${BOLD}${BLUE}============================================================${RESET}"
echo -e "${BOLD}${BLUE} 🛡️  Docker Sandbox Protocol: Automated Installer 🛡️${RESET}"
echo -e "${BOLD}${BLUE}============================================================${RESET}\n"

# 1. Dependency Checks
echo -e "${BOLD}🔍 Checking system prerequisites...${RESET}"

if ! command -v docker &>/dev/null; then
    echo -e "${RED}❌ Docker is not installed or not in PATH.${RESET}"
    echo "   Please install Docker Engine before continuing: https://docs.docker.com/engine/install/"
    exit 1
fi
echo -e "  ✅ Docker is installed: $(docker --version)"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}❌ Python 3 is not installed or not in PATH.${RESET}"
    exit 1
fi
echo -e "  ✅ Python 3 is installed: $(python3 --version)"

# Check Docker socket permissions
if ! docker ps &>/dev/null; then
    echo -e "${YELLOW}⚠️  Warning: Cannot communicate with Docker daemon.${RESET}"
    echo -e "   If you need non-root docker access, run: ${BOLD}sudo usermod -aG docker \$USER${RESET} and log back in."
fi

# 2. Permissions on Repository Scripts
echo -e "\n${BOLD}🔑 Setting executable permissions on scripts...${RESET}"
chmod +x "$REPO_DIR/bin/sandbox"
chmod +x "$REPO_DIR/config/containers_cli.py"
chmod +x "$REPO_DIR/config/proxy.py"
chmod +x "$REPO_DIR/scripts/"*.sh
chmod +x "$REPO_DIR/tools/"*.sh 2>/dev/null || true
chmod +x "$REPO_DIR/tools/"*.py 2>/dev/null || true
echo -e "  ✅ Executable bits set."

# 3. Initialize Configuration Files from Examples
echo -e "\n${BOLD}📝 Initializing local configuration files...${RESET}"
CONFIG_DIR="$REPO_DIR/config"

init_config() {
    local example_file="$1"
    local target_file="$2"
    local secure_perms="$3"

    if [ ! -f "$target_file" ]; then
        if [ -f "$example_file" ]; then
            cp "$example_file" "$target_file"
            if [ "$secure_perms" = "true" ]; then
                chmod 600 "$target_file"
            fi
            echo -e "  ✨ Created $(basename "$target_file") from example"
        fi
    else
        echo -e "  ℹ️  $(basename "$target_file") already exists (preserved)"
    fi
}

init_config "$CONFIG_DIR/containers_settings.example.json" "$CONFIG_DIR/containers_settings.json" "false"
init_config "$CONFIG_DIR/container_groupings.example.json" "$CONFIG_DIR/container_groupings.json" "false"
init_config "$CONFIG_DIR/containers_permissions.example.json" "$CONFIG_DIR/containers_permissions.json" "false"
init_config "$CONFIG_DIR/agent_secrets_vault.example.json" "$CONFIG_DIR/agent_secrets_vault.json" "true"

# 4. Create Standard Directories
echo -e "\n${BOLD}📂 Preparing default sandbox directories...${RESET}"
mkdir -p "$HOME/sandbox/workspace"
mkdir -p "$HOME/sandbox/scratch"
echo -e "  ✅ Directories verified: ~/sandbox/workspace, ~/sandbox/scratch"

# 5. CLI Link Installation
echo -e "\n${BOLD}🔗 Installing 'sandbox' CLI command...${RESET}"
TARGET_LINK="/usr/local/bin/sandbox"

if [ -w "/usr/local/bin" ]; then
    ln -sf "$REPO_DIR/bin/sandbox" "$TARGET_LINK"
    echo -e "  ✅ Symlinked '$REPO_DIR/bin/sandbox' -> '$TARGET_LINK'"
elif command -v sudo &>/dev/null; then
    echo "  Prompting for sudo to install to /usr/local/bin/sandbox..."
    sudo ln -sf "$REPO_DIR/bin/sandbox" "$TARGET_LINK"
    echo -e "  ✅ Symlinked to '$TARGET_LINK' via sudo"
else
    # Fallback to ~/.local/bin
    USER_BIN="$HOME/.local/bin"
    mkdir -p "$USER_BIN"
    ln -sf "$REPO_DIR/bin/sandbox" "$USER_BIN/sandbox"
    echo -e "  ✅ Symlinked to '$USER_BIN/sandbox' (ensure ~/.local/bin is in your PATH)"
fi

# 6. Build Base Container Image
echo -e "\n${BOLD}🐳 Building base container image 'agent-sandbox'...${RESET}"
if docker build -t agent-sandbox "$CONFIG_DIR"; then
    echo -e "  🎉 Base image 'agent-sandbox' built successfully!"
else
    echo -e "${YELLOW}⚠️  Image build had warnings or failed. You can build manually later via 'sandbox rebuild'.${RESET}"
fi

# 7. Verification
echo -e "\n${BOLD}🚀 Running system verification check...${RESET}"
"$REPO_DIR/bin/sandbox" status

echo -e "\n${BOLD}${GREEN}============================================================${RESET}"
echo -e "${BOLD}${GREEN} 🎉 Docker Sandbox Protocol installation complete!${RESET}"
echo -e "${BOLD}${GREEN}============================================================${RESET}\n"
echo -e "Quick Start Commands:"
echo -e "  ${BOLD}sandbox status${RESET}               # View container dashboard"
echo -e "  ${BOLD}sandbox start dev-sandbox${RESET}    # Start development sandbox"
echo -e "  ${BOLD}sandbox enter dev-sandbox${RESET}    # Enter interactive shell"
echo -e "  ${BOLD}sandbox explain dev-sandbox${RESET}  # Inspect container lifecycle"
echo -e "  ${BOLD}sandbox edit${RESET}                 # Open configuration in your editor\n"
