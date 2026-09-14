#!/usr/bin/env python3
import sys
import os
import subprocess
import json
import pwd
import shutil
import socket

# Dynamically resolve root and configuration paths
REAL_FILE = os.path.realpath(__file__)
REAL_DIR = os.path.dirname(REAL_FILE)
if REAL_DIR not in sys.path:
    sys.path.insert(0, REAL_DIR)

import lifecycle_action_validator

# If placed in config/, ROOT is the parent directory; otherwise ROOT is REAL_DIR
ROOT_DIR = os.environ.get("SANDBOX_ROOT", os.path.dirname(REAL_DIR) if os.path.basename(REAL_DIR) == "config" else REAL_DIR)

CONFIG_DIR = os.environ.get("SANDBOX_CONFIG_DIR", os.path.join(ROOT_DIR, "config"))
SETTINGS_FILE = os.environ.get("SANDBOX_SETTINGS_FILE", os.path.join(CONFIG_DIR, "containers_settings.json"))
SETTINGS_EXAMPLE_FILE = os.path.join(CONFIG_DIR, "containers_settings.example.json")
DOCKERFILE = os.path.join(CONFIG_DIR, "Dockerfile")
IMAGE_NAME = os.environ.get("SANDBOX_IMAGE_NAME", "agent-sandbox")
RULES_FILE = os.environ.get("SANDBOX_PROXY_RULES", "/tmp/sandbox_proxy_rules.json")
GROUPINGS_FILE = os.environ.get("SANDBOX_GROUPINGS_FILE", os.path.join(CONFIG_DIR, "container_groupings.json"))
GROUPINGS_EXAMPLE_FILE = os.path.join(CONFIG_DIR, "container_groupings.example.json")
PRESETS_FILE = os.environ.get("SANDBOX_PRESETS_FILE", os.path.join(ROOT_DIR, "presets", "presets.json"))

# Colors for premium visual formatting
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_header(title):
    print(f"\n{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{BLUE} 🛡️  {title} 🛡️{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}\n")

def expand_path(p):
    """Expands ~, environment variables, and returns absolute path."""
    if not p:
        return p
    return os.path.abspath(os.path.expanduser(os.path.expandvars(p)))

def get_groupings_path():
    if os.path.exists(GROUPINGS_FILE):
        return GROUPINGS_FILE
    if os.path.exists(GROUPINGS_EXAMPLE_FILE):
        return GROUPINGS_EXAMPLE_FILE
    return None

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        if os.path.exists(SETTINGS_EXAMPLE_FILE):
            print(f"{YELLOW}⚠️  Notice: Active configuration '{SETTINGS_FILE}' not found.{RESET}")
            print(f"{YELLOW}    Using example configuration '{SETTINGS_EXAMPLE_FILE}'.{RESET}")
            print(f"{YELLOW}    Tip: Copy '{SETTINGS_EXAMPLE_FILE}' to '{SETTINGS_FILE}' to customize.{RESET}\n")
            with open(SETTINGS_EXAMPLE_FILE, "r") as f:
                return json.load(f)
        else:
            print(f"{RED}❌ Error: Configuration file not found at {SETTINGS_FILE}{RESET}")
            sys.exit(1)
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

def get_compose_bin():
    env_bin = os.environ.get("DOCKER_COMPOSE_BIN")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    which_compose = shutil.which("docker-compose")
    if which_compose:
        return which_compose
    fallbacks = [
        os.path.expanduser("~/Apps/Binaries/docker-compose"),
        "/usr/local/bin/docker-compose",
        "/usr/bin/docker-compose"
    ]
    for fb in fallbacks:
        if os.path.exists(fb):
            return fb
    return "docker-compose"

def execute_lifecycle_step(phase, step, container_name=None):
    registry = lifecycle_action_validator.load_registry()
    action_name = step.get("@action")
    action_meta = registry["actions"][action_name]
    script_name = action_meta["script"]
    script_path = os.path.join(lifecycle_action_validator.SCRIPTS_DIR, script_name)
    
    cmd = [script_path]
    for key, val in step.items():
        if key == "@action":
            continue
        if isinstance(val, bool):
            cmd.extend([f"--{key}", "true" if val else "false"])
        elif isinstance(val, list):
            for item in val:
                cmd.extend([f"--{key}", str(item)])
        else:
            # Expand paths if key suggests filesystem path
            str_val = expand_path(str(val)) if "path" in key else str(val)
            cmd.extend([f"--{key}", str_val])
        
    if action_meta.get("runs_on") == "container" and container_name:
        cmd.extend(["--container", container_name])
        
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"{RED}❌ Error executing lifecycle action '{action_name}' in phase '{phase}':{RESET}")
        print(res.stderr)
        sys.exit(1)
    else:
        if res.stdout:
            print(f"    {res.stdout.strip()}")

def run_healthchecks(agent, container_name):
    lifecycle = lifecycle_action_validator.normalize_lifecycle(agent)
    healthcheck = lifecycle.get("healthcheck", [])
    if healthcheck:
        print(f"{GREEN}🔍 Running healthchecks for '{agent.get('name')}'...{RESET}")
        for i, step in enumerate(healthcheck):
            action_name = step.get("@action")
            print(f"  Verifying step [{i}]: {action_name}")
            execute_lifecycle_step("healthcheck", step, container_name)

def parse_version(v_str):
    v_str = v_str.strip().lower()
    if v_str.startswith('v'):
        v_str = v_str[1:]
    parts = []
    for part in v_str.split('.'):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(part)
    return parts

def compare_versions(v1, v2):
    p1 = parse_version(v1)
    p2 = parse_version(v2)
    for i in range(max(len(p1), len(p2))):
        el1 = p1[i] if i < len(p1) else 0
        el2 = p2[i] if i < len(p2) else 0
        if type(el1) != type(el2):
            el1, el2 = str(el1), str(el2)
        if el1 < el2:
            return -1
        elif el1 > el2:
            return 1
    return 0

def match_version(version, specifier):
    specifier = specifier.strip()
    if not specifier:
        return True
    operators = [">=", "<=", "==", "!=", ">", "<", "~"]
    op = ""
    for o in operators:
        if specifier.startswith(o):
            op = o
            val = specifier[len(o):].strip()
            break
    else:
        op = "=="
        val = specifier
    if val.startswith('v'):
        val = val[1:]
    if op == "==":
        return compare_versions(version, val) == 0
    elif op == "!=":
        return compare_versions(version, val) != 0
    elif op == ">=":
        return compare_versions(version, val) >= 0
    elif op == "<=":
        return compare_versions(version, val) <= 0
    elif op == ">":
        return compare_versions(version, val) > 0
    elif op == "<":
        return compare_versions(version, val) < 0
    elif op == "~":
        p_val = parse_version(val)
        p_ver = parse_version(version)
        if len(p_val) == 1:
            return p_ver[0] == p_val[0] and compare_versions(version, val) >= 0
        elif len(p_val) >= 2:
            return p_ver[0] == p_val[0] and p_ver[1] == p_val[1] and compare_versions(version, val) >= 0
    return False

def resolve_requirements(requirements):
    if not os.path.exists(PRESETS_FILE):
        print(f"{YELLOW}⚠️  Warning: Presets file not found at {PRESETS_FILE}. Skipping requirements.{RESET}")
        return [], {}
        
    with open(PRESETS_FILE, "r") as f:
        presets = json.load(f)
        
    install_commands = []
    env_vars = {}
    
    for req in requirements:
        req = req.strip()
        if not req:
            continue
            
        parts = req.split(None, 1)
        name = parts[0]
        specifier = parts[1].strip() if len(parts) > 1 else ""
        
        if name not in presets:
            print(f"{YELLOW}⚠️  Warning: Preset package '{name}' not found in presets.json. Skipping.{RESET}")
            continue
            
        preset_info = presets[name]
        versions_dict = preset_info.get("versions", {})
        default_version = preset_info.get("default_version", "")
        
        is_default_or_any = specifier in ["", "*", "default"]
        
        if is_default_or_any:
            if default_version in versions_dict:
                selected_version = default_version
                print(f"📦 [Preset Manager] Resolved '{req}' ➡️ default version '{selected_version}'")
            elif versions_dict:
                sorted_vers = sorted(versions_dict.keys(), key=lambda x: parse_version(x))
                selected_version = sorted_vers[-1]
                print(f"📦 [Preset Manager] Resolved '{req}' ➡️ latest version '{selected_version}'")
            else:
                print(f"{RED}❌ Error: No versions defined for preset '{name}'. Skipping.{RESET}")
                continue
        else:
            matching_versions = [v for v in versions_dict.keys() if match_version(v, specifier)]
            if not matching_versions:
                if default_version in versions_dict:
                    selected_version = default_version
                    print(f"📦 [Preset Manager] No match for '{req}'. Falling back to default version '{selected_version}'.")
                elif versions_dict:
                    sorted_vers = sorted(versions_dict.keys(), key=lambda x: parse_version(x))
                    selected_version = sorted_vers[-1]
                    print(f"📦 [Preset Manager] No match for '{req}'. Falling back to highest version '{selected_version}'.")
                else:
                    print(f"{RED}❌ Error: No versions defined for preset '{name}'. Skipping.{RESET}")
                    continue
            else:
                sorted_matching = sorted(matching_versions, key=lambda x: parse_version(x))
                selected_version = sorted_matching[-1]
                print(f"📦 [Preset Manager] Resolved '{req}' ➡️ version '{selected_version}'")
            
        version_details = versions_dict[selected_version]
        cmd = version_details.get("command")
        if cmd:
            install_commands.append(cmd)
        env = version_details.get("env", {})
        env_vars.update(env)
        
    return install_commands, env_vars

def build_custom_image(agent_name, requirements):
    custom_image_name = f"{IMAGE_NAME}-{agent_name}"
    print(f"📦 [Preset Manager] Resolving container requirements for '{agent_name}'...")
    
    install_commands, env_vars = resolve_requirements(requirements)
    if not install_commands and not env_vars:
        print(f"📦 [Preset Manager] No installations or env vars required. Reverting to base image.")
        return IMAGE_NAME
        
    dockerfile_lines = [
        f"FROM {IMAGE_NAME}",
        "USER root",
        "ENV DEBIAN_FRONTEND=noninteractive"
    ]
    
    for cmd in install_commands:
        dockerfile_lines.append(f"RUN {cmd}")
        
    for k, v in env_vars.items():
        dockerfile_lines.append(f"ENV {k}={v}")
        
    dockerfile_lines.append("USER agent")
    
    dockerfile_content = "\n".join(dockerfile_lines)
    
    build_dir = "/tmp/sandbox-custom-build"
    os.makedirs(build_dir, exist_ok=True)
    tmp_dockerfile_path = os.path.join(build_dir, "Dockerfile")
    with open(tmp_dockerfile_path, "w") as f:
        f.write(dockerfile_content)
        
    res = subprocess.run(["docker", "build", "-t", custom_image_name, build_dir])
    
    shutil.rmtree(build_dir, ignore_errors=True)
    
    if res.returncode == 0:
        print(f"🎉 [Preset Manager] Custom image '{custom_image_name}' built successfully!")
        return custom_image_name
    else:
        print(f"{RED}❌ Error: Failed to build custom image. Falling back to base image '{IMAGE_NAME}'.{RESET}")
        return IMAGE_NAME

def get_container_config(settings, name):
    containers = settings.get("containers") or settings.get("agents", [])
    for container in containers:
        if container.get("name") == name:
            return container
    return None

def get_default_container():
    grp_file = get_groupings_path()
    if grp_file:
        try:
            with open(grp_file, "r") as f:
                groupings = json.load(f)
            grp_data = groupings.get("container_groupings", {})
            for grp, info in grp_data.items():
                default_c = info.get("default_container")
                if default_c:
                    return default_c
        except Exception:
            pass
    return "dev-sandbox"

def resolve_container_name(name):
    grp_file = get_groupings_path()
    if grp_file:
        try:
            with open(grp_file, "r") as f:
                groupings = json.load(f)
            grp_data = groupings.get("container_groupings", {})
            for grp, info in grp_data.items():
                if name in info.get("containers", []):
                    naming = info.get("naming", {})
                    prefix = naming.get("prefix", "")
                    suffix = naming.get("suffix", "")
                    return f"{prefix}{name}{suffix}"
        except Exception:
            pass
    return name

def is_container_running(container_name):
    res = subprocess.run(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"], capture_output=True, text=True)
    return container_name in res.stdout.splitlines()

def is_container_exists(container_name):
    res = subprocess.run(["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"], capture_output=True, text=True)
    return container_name in res.stdout.splitlines()

def get_container_ip(container_name):
    res = subprocess.run(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_name], capture_output=True, text=True)
    return res.stdout.strip()

def register_proxy_rules(container_name, allowed_domains, allowed_containers=None):
    if allowed_containers is None:
        allowed_containers = ["*"]
    container_ip = get_container_ip(container_name)
    if container_ip:
        rules = {}
        if os.path.exists(RULES_FILE):
            try:
                with open(RULES_FILE, "r") as f:
                    rules = json.load(f)
            except Exception:
                pass
        
        if "container_ips" not in rules:
            rules["container_ips"] = {}
        
        rules["container_ips"][container_ip] = container_name
        rules[container_ip] = {
            "domains": allowed_domains,
            "containers": allowed_containers
        }
        
        try:
            settings = load_settings()
            containers = settings.get("containers") or settings.get("agents", [])
            for c in containers:
                c_name = c.get("name")
                resolved_c_name = resolve_container_name(c_name)
                if resolved_c_name != container_name and is_container_running(resolved_c_name):
                    ip = get_container_ip(resolved_c_name)
                    if ip:
                        rules["container_ips"][ip] = resolved_c_name
        except Exception:
            pass
            
        with open(RULES_FILE, "w") as f:
            json.dump(rules, f, indent=2)

def unregister_proxy_rules(container_name):
    container_ip = get_container_ip(container_name)
    if container_ip and os.path.exists(RULES_FILE):
        try:
            with open(RULES_FILE, "r") as f:
                rules = json.load(f)
            if container_ip in rules:
                del rules[container_ip]
            if "container_ips" in rules and container_ip in rules["container_ips"]:
                del rules["container_ips"][container_ip]
            with open(RULES_FILE, "w") as f:
                json.dump(rules, f, indent=2)
        except Exception:
            pass

def register_container_ip(container_name):
    container_ip = get_container_ip(container_name)
    if container_ip:
        rules = {}
        if os.path.exists(RULES_FILE):
            try:
                with open(RULES_FILE, "r") as f:
                    rules = json.load(f)
            except Exception:
                pass
        if "container_ips" not in rules:
            rules["container_ips"] = {}
            
        rules["container_ips"][container_ip] = container_name
        with open(RULES_FILE, "w") as f:
            json.dump(rules, f, indent=2)

def ensure_proxy_running():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", 8888))
        s.close()
        # Port is free, start the proxy in background
        proxy_path = os.path.join(CONFIG_DIR, "proxy.py")
        if os.path.exists(proxy_path):
            subprocess.Popen([sys.executable, proxy_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=os.environ.copy())
            print("🛡️  [Orchestrator] Started Sandbox Filter Proxy in background.")
    except socket.error:
        # Already running
        pass

def do_build():
    if not os.path.exists(DOCKERFILE):
        print(f"{RED}❌ Error: Dockerfile not found at {DOCKERFILE}{RESET}")
        sys.exit(1)
    print(f"{GREEN}⚡ Building core agent image '{IMAGE_NAME}'...{RESET}")
    res = subprocess.run(["docker", "build", "-t", IMAGE_NAME, CONFIG_DIR])
    if res.returncode != 0:
        print(f"{RED}❌ Error: Docker image build failed.{RESET}")
        sys.exit(1)
    print(f"{GREEN}🎉 Image built successfully!{RESET}")

def setup_and_run_startup(agent, container_name):
    subprocess.run(["docker", "exec", "-u", "root", container_name, "touch", "/var/log/sandbox_startup.log"])
    subprocess.run(["docker", "exec", "-u", "root", container_name, "chmod", "666", "/var/log/sandbox_startup.log"])
    subprocess.run(["docker", "exec", "-u", "root", container_name, "sh", "-c", "echo \"[$(date '+%Y-%m-%d %H:%M:%S')] Container booted / started\" >> /var/log/sandbox_startup.log"])

    lifecycle = lifecycle_action_validator.normalize_lifecycle(agent)
    container_startup = lifecycle.get("container_startup", {})
    behavior = container_startup.get("behavior", "NEVER").upper()
    steps = container_startup.get("steps", [])
    
    commands = []
    for step in steps:
        if step.get("@action") == "shell":
            commands.append(step.get("command"))

    behavior_content = f"Startup Behavior: {behavior}\n"
    subprocess.run(["docker", "exec", "-u", "root", "-i", container_name, "sh", "-c", "cat > /etc/sandbox_behavior"], input=behavior_content, text=True)

    sandbox_script = r"""#!/bin/bash
LOG_FILE="/var/log/sandbox_startup.log"
STARTUP_SCRIPT="/usr/local/bin/startup.sh"
BEHAVIOR_FILE="/etc/sandbox_behavior"

case "$1" in
    start)
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Manual startup sequence initiated by user" >> "$LOG_FILE"
        if [ ! -f "$STARTUP_SCRIPT" ]; then
            echo "Error: Startup script $STARTUP_SCRIPT not found." | tee -a "$LOG_FILE"
            exit 1
        fi
        echo "Starting background services defined in $STARTUP_SCRIPT..."
        nohup bash "$STARTUP_SCRIPT" >> "$LOG_FILE" 2>&1 &
        echo "Startup sequence triggered. Check logs with 'sandbox log'."
        ;;
    log)
        if [ -f "$LOG_FILE" ]; then
            cat "$LOG_FILE"
        else
            echo "No startup logs found at $LOG_FILE"
        fi
        ;;
    runtime)
        echo "============================================================"
        echo " ⚙️  SANDBOX CONTAINER RUNTIME INFO"
        echo "============================================================"
        if [ -f "$BEHAVIOR_FILE" ]; then
            cat "$BEHAVIOR_FILE"
        else
            echo "Startup Behavior: NOT CONFIGURED"
        fi
        echo "Startup Script: $STARTUP_SCRIPT"
        echo "------------------------------------------------------------"
        echo "Startup Script Contents:"
        if [ -f "$STARTUP_SCRIPT" ]; then
            cat "$STARTUP_SCRIPT"
        else
            echo "[None]"
        fi
        echo "============================================================"
        ;;
    *)
        echo "Usage: sandbox {start|log|runtime}"
        echo "       container {start|log|runtime}"
        exit 1
        ;;
esac
"""
    subprocess.run(["docker", "exec", "-u", "root", "-i", container_name, "sh", "-c", "cat > /usr/local/bin/sandbox"], input=sandbox_script, text=True)
    subprocess.run(["docker", "exec", "-u", "root", container_name, "chmod", "+x", "/usr/local/bin/sandbox"])
    subprocess.run(["docker", "exec", "-u", "root", container_name, "ln", "-sf", "/usr/local/bin/sandbox", "/usr/local/bin/container"])

    startup_script_lines = [
        "#!/bin/bash",
        f"echo \"[$(date '+%Y-%m-%d %H:%M:%S')] --- Startup Script Execution Started ---\"",
    ]
    if commands:
        for cmd in commands:
            startup_script_lines.append(f"echo \"[$(date '+%Y-%m-%d %H:%M:%S')] Executing: {cmd}\"")
            startup_script_lines.append(cmd)
    else:
        startup_script_lines.append("echo \"No startup commands configured.\"")
        
    startup_script_lines.append(f"echo \"[$(date '+%Y-%m-%d %H:%M:%S')] --- Startup Script Execution Completed ---\"")
    startup_script_content = "\n".join(startup_script_lines) + "\n"
    
    subprocess.run(["docker", "exec", "-u", "root", "-i", container_name, "sh", "-c", "cat > /usr/local/bin/startup.sh"], input=startup_script_content, text=True)
    subprocess.run(["docker", "exec", "-u", "root", container_name, "chmod", "+x", "/usr/local/bin/startup.sh"])

    runtime_config = agent.get("runtime", {})
    run_as_root = runtime_config.get("run_as_root", False)
    exec_cmd = ["docker", "exec"]
    if run_as_root:
        exec_cmd += ["-u", "root"]
    exec_cmd += ["-d", container_name, "/usr/local/bin/sandbox", "start"]

    if behavior == "ALWAYS":
        print(f"🔄 Automatically triggering startup script for '{container_name}' (ALWAYS, run_as_root={run_as_root})...")
        subprocess.run(exec_cmd)
    elif behavior == "ONCE":
        check_res = subprocess.run(["docker", "exec", container_name, "test", "-f", "/var/lib/sandbox_startup_done"])
        if check_res.returncode != 0:
            print(f"🔄 Automatically triggering startup script for '{container_name}' (ONCE - first boot, run_as_root={run_as_root})...")
            subprocess.run(exec_cmd)
            subprocess.run(["docker", "exec", "-u", "root", container_name, "touch", "/var/lib/sandbox_startup_done"])
        else:
            print(f"ℹ️  Startup script for '{container_name}' already executed once in this container lifetime. Skipping.")
            log_msg = "[$(date '+%Y-%m-%d %H:%M:%S')] Startup script skipped because it already executed once (ONCE behavior)"
            subprocess.run(["docker", "exec", container_name, "sh", "-c", f"echo \"{log_msg}\" >> /var/log/sandbox_startup.log"])
    else:
        log_msg = "[$(date '+%Y-%m-%d %H:%M:%S')] Startup script skipped (NEVER behavior)"
        subprocess.run(["docker", "exec", container_name, "sh", "-c", f"echo \"{log_msg}\" >> /var/log/sandbox_startup.log"])

def parse_network_settings(agent):
    ports_to_bind = []
    allow_host = True
    allow_external = ["*"]
    allow_containers = ["*"]
    
    network_config = agent.get("network", {})
    
    if isinstance(network_config, dict) and ("host_access" in network_config or "external_access" in network_config or "container_access" in network_config):
        allow_external = network_config.get("external_access", [])
        allow_containers = network_config.get("container_access", ["*"])
        
        host_access = network_config.get("host_access", {})
        if isinstance(host_access, dict):
            allow_host = host_access.get("enabled", True)
            allowed_ports = host_access.get("allowed_ports", [])
            
            if "published_port_scope" in host_access:
                scope = host_access.get("published_port_scope", "public").lower()
            else:
                deny_private_lan = host_access.get("deny_private_lan", False)
                scope = "loopback" if deny_private_lan else "public"
            
            if scope != "none":
                for port_item in allowed_ports:
                    is_loopback = (scope == "loopback")
                    if isinstance(port_item, int):
                        if is_loopback:
                            ports_to_bind.append(f"127.0.0.1:{port_item}:{port_item}")
                        else:
                            ports_to_bind.append(f"{port_item}:{port_item}")
                    elif isinstance(port_item, str):
                        if ":" not in port_item:
                            p_num = port_item
                            if is_loopback:
                                ports_to_bind.append(f"127.0.0.1:{p_num}:{p_num}")
                            else:
                                ports_to_bind.append(f"{p_num}:{p_num}")
                        else:
                            parts = port_item.split(":")
                            if len(parts) == 2:
                                if is_loopback:
                                    ports_to_bind.append(f"127.0.0.1:{port_item}")
                                else:
                                    ports_to_bind.append(port_item)
                            else:
                                ports_to_bind.append(port_item)
        else:
            allow_host = bool(host_access)
    else:
        allow_host = network_config.get("allow_host", agent.get("toggle_network", True))
        allow_external = network_config.get("allow_external", ["*"] if agent.get("toggle_network", True) else [])
        allow_containers = network_config.get("allow_containers", ["*"])
        ports_to_bind = agent.get("ports", [])
        
    return allow_host, allow_external, allow_containers, ports_to_bind

def start_agent(agent):
    name = agent.get("name")
    container_name = resolve_container_name(name)
    
    if not agent.get("enabled", True):
        print(f"{YELLOW}⚠️  Agent '{name}' is disabled in settings. Skipping.{RESET}")
        return

    # Run host_prepare actions if not already running
    if not is_container_running(container_name):
        lifecycle = lifecycle_action_validator.normalize_lifecycle(agent)
        host_prepare = lifecycle.get("host_prepare", [])
        if host_prepare:
            print(f"{GREEN}⚙️  Running validated host_prepare actions for '{name}'...{RESET}")
            for i, step in enumerate(host_prepare):
                action_name = step.get("@action")
                print(f"  Executing step [{i}]: {action_name}")
                execute_lifecycle_step("host_prepare", step, container_name)

    # Check if compose_path is specified for native stack unionization
    compose_path = agent.get("compose_path")
    if compose_path:
        compose_path = expand_path(compose_path)
        if not os.path.exists(compose_path):
            print(f"{RED}❌ Error: Compose file '{compose_path}' not found.{RESET}")
            return
        
        if is_container_running(container_name):
            print(f"{GREEN}🟢 Container '{container_name}' is already running via Compose.{RESET}")
            return
            
        print(f"{GREEN}🚀 Starting native Docker Compose stack from '{compose_path}'...{RESET}")
        compose_bin = get_compose_bin()
            
        res = subprocess.run([compose_bin, "-f", compose_path, "up", "-d"])
        if res.returncode == 0:
            print(f"🎉 {GREEN}Docker Compose stack successfully launched!{RESET}")
            run_healthchecks(agent, container_name)
        else:
            print(f"{RED}❌ Error: Failed to start docker-compose stack.{RESET}")
        return

    # Check if already running
    if is_container_running(container_name):
        print(f"{GREEN}🟢 Agent '{name}' is already running in container '{container_name}'.{RESET}")
        return
        
    # Check if exists but stopped
    if is_container_exists(container_name):
        print(f"{GREEN}⚡ Starting stopped container '{container_name}'...{RESET}")
        subprocess.run(["docker", "start", container_name])
        
        allow_host, allow_external, allow_containers, _ = parse_network_settings(agent)
        if allow_host and (allow_external != ["*"] or allow_containers != ["*"]):
            register_proxy_rules(container_name, allow_external, allow_containers)
            ensure_proxy_running()
            subprocess.run(["docker", "exec", container_name, "ip", "route", "del", "default"], capture_output=True)
        else:
            register_container_ip(container_name)
            
        if not agent.get("image"):
            setup_and_run_startup(agent, container_name)
        run_healthchecks(agent, container_name)
        return

    custom_image = agent.get("image")
    if custom_image:
        active_image = custom_image
    else:
        requirements = agent.get("requirements", [])
        active_image = IMAGE_NAME
        if requirements:
            do_build()
            active_image = build_custom_image(name, requirements)

    print(f"{GREEN}🚀 Creating and starting sandbox container '{container_name}' using image '{active_image}'...{RESET}")

    # Build workspace and scratch paths if they don't exist
    for path_key in ["workspace_path", "scratch_path"]:
        raw_path = agent.get(path_key)
        if raw_path:
            path = expand_path(raw_path)
            if not os.path.exists(path):
                print(f"  📂 Creating local directory: {path}")
                os.makedirs(path, exist_ok=True)
                try:
                    shutil.chown(path, user=1001, group=1001)
                except Exception:
                    try:
                        os.chmod(path, 0o777)
                    except Exception:
                        pass

    # Base docker run command
    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "--restart", "unless-stopped",
    ]
    
    # Volumes support
    volumes = agent.get("volumes")
    if volumes is not None:
        for vol in volumes:
            cmd += ["-v", vol]
    else:
        # Standard sandbox mounts
        agent_home = os.environ.get("SANDBOX_AGENT_HOME", "/home/agentic")
        if os.path.exists(agent_home):
            cmd += ["-v", f"{agent_home}:/home/agent"]
        if agent.get("workspace_path"):
            cmd += ["-v", f"{expand_path(agent.get('workspace_path'))}:/workspace"]
        if agent.get("scratch_path"):
            cmd += ["-v", f"{expand_path(agent.get('scratch_path'))}:/scratch"]

    # CPU and Memory Limits
    if agent.get("cpu_limit"):
        cmd += ["--cpus", str(agent.get("cpu_limit"))]
    if agent.get("memory_limit"):
        cmd += ["--memory", str(agent.get("memory_limit"))]

    allow_host, allow_external, allow_containers, ports = parse_network_settings(agent)

    # Auto-inject running containers into /etc/hosts
    if allow_containers:
        try:
            inspect_res = subprocess.run(
                ["docker", "ps", "-q"],
                capture_output=True, text=True, check=True
            )
            container_ids = inspect_res.stdout.strip().split()
            if container_ids:
                inspect_info = subprocess.run(
                    ["docker", "inspect"] + container_ids,
                    capture_output=True, text=True, check=True
                )
                containers_data = json.loads(inspect_info.stdout)
                for c in containers_data:
                    c_name = c["Name"].lstrip("/")
                    if c_name != container_name:
                        networks = c.get("NetworkSettings", {}).get("Networks", {})
                        for net_name, net_info in networks.items():
                            ip = net_info.get("IPAddress")
                            if ip:
                                cmd += ["--add-host", f"{c_name}:{ip}"]
                                if c_name.startswith("agent-"):
                                    cmd += ["--add-host", f"{c_name[6:]}:{ip}"]
                                break
        except Exception as e:
            pass

    # Ports support
    for port in ports:
        cmd += ["-p", port]

    security_config = agent.get("security", {})
    allow_sudo = security_config.get("allow_sudo", agent.get("toggle_sudo", False))
    allow_google_auth = security_config.get("allow_google_auth", agent.get("toggle_google_auth", False))
    
    if not allow_host and not allow_external:
        cmd += ["--network", "none"]
    elif allow_host and (allow_external != ["*"] or allow_containers != ["*"]):
        cmd += ["--cap-add", "NET_ADMIN"]
        if allow_containers == ["*"]:
            no_proxy_val = "localhost,127.0.0.1,172.17.0.1,172.17.0.0/16,172.18.0.0/16,172.19.0.0/16,172.20.0.0/16"
        else:
            no_proxy_val = "localhost,127.0.0.1,172.17.0.1"
            
        cmd += [
            "-e", "http_proxy=http://172.17.0.1:8888",
            "-e", "https_proxy=http://172.17.0.1:8888",
            "-e", "HTTP_PROXY=http://172.17.0.1:8888",
            "-e", "HTTPS_PROXY=http://172.17.0.1:8888",
            "-e", f"no_proxy={no_proxy_val}"
        ]

    # Environment variables support
    env_vars = agent.get("environment", {})
    if isinstance(env_vars, dict):
        for k, v in env_vars.items():
            cmd += ["-e", f"{k}={v}"]
    elif isinstance(env_vars, list):
        for env_item in env_vars:
            cmd += ["-e", env_item]

    # Toggle Sudo Capability (/dev/null mount)
    if not allow_sudo:
        cmd += ["-v", "/dev/null:/usr/bin/sudo:ro"]

    # Toggle Google Authenticator OTP Mount
    if allow_google_auth:
        otp_file = "/var/lib/google-authenticator/agentic"
        if os.path.exists(otp_file):
            cmd += ["-v", f"{otp_file}:/etc/security/google-authenticator/agent:ro"]
        else:
            print(f"{YELLOW}⚠️  Warning: Google Authenticator key file not found on host. Skipping OTP mount.{RESET}")

    cmd += [active_image]

    # Custom Command Support
    if "command" in agent:
        custom_cmd = agent["command"]
        if isinstance(custom_cmd, list):
            cmd += custom_cmd
        elif isinstance(custom_cmd, str) and custom_cmd:
            import shlex
            cmd += shlex.split(custom_cmd)
    elif not custom_image:
        cmd += ["tail", "-f", "/dev/null"]

    res = subprocess.run(cmd)
    if res.returncode == 0:
        print(f"🎉 {GREEN}Agent '{name}' successfully containerized and started!{RESET}")
        
        if allow_host and (allow_external != ["*"] or allow_containers != ["*"]):
            register_proxy_rules(container_name, allow_external, allow_containers)
            ensure_proxy_running()
            subprocess.run(["docker", "exec", container_name, "ip", "route", "del", "default"], capture_output=True)
        else:
            register_container_ip(container_name)
            
        if not custom_image:
            setup_and_run_startup(agent, container_name)
        run_healthchecks(agent, container_name)
    else:
        print(f"{RED}❌ Error: Failed to start container for agent '{name}'.{RESET}")

def stop_agent(agent):
    name = agent.get("name")
    container_name = resolve_container_name(name)
    
    compose_path = agent.get("compose_path")
    if compose_path:
        compose_path = expand_path(compose_path)
        if not os.path.exists(compose_path):
            print(f"{RED}❌ Error: Compose file '{compose_path}' not found.{RESET}")
            return
        print(f"{RED}🛑 Stopping native Docker Compose stack from '{compose_path}'...{RESET}")
        compose_bin = get_compose_bin()
            
        res = subprocess.run([compose_bin, "-f", compose_path, "down"])
        if res.returncode == 0:
            print(f"🧹 {GREEN}Docker Compose stack successfully stopped and removed!{RESET}")
        else:
            print(f"{RED}❌ Error: Failed to stop docker-compose stack.{RESET}")
        return

    if not is_container_exists(container_name):
        print(f"{YELLOW}⚠️  Agent container '{container_name}' does not exist.{RESET}")
        return

    if is_container_running(container_name):
        lifecycle = lifecycle_action_validator.normalize_lifecycle(agent)
        shutdown_steps = lifecycle.get("shutdown", [])
        if shutdown_steps:
            print(f"{GREEN}⚙️  Running validated shutdown actions for '{name}'...{RESET}")
            for i, step in enumerate(shutdown_steps):
                action_name = step.get("@action")
                print(f"  Executing shutdown step [{i}]: {action_name}")
                execute_lifecycle_step("shutdown", step, container_name)

    print(f"{RED}🛑 Stopping and removing container '{container_name}'...{RESET}")
    unregister_proxy_rules(container_name)
    
    subprocess.run(["docker", "stop", container_name], capture_output=True)
    subprocess.run(["docker", "rm", container_name], capture_output=True)
    print(f"🧹 {GREEN}Container '{container_name}' completely removed.{RESET}")

def do_enter(agent_name):
    settings = load_settings()
    if agent_name == "*":
        print(f"{RED}❌ Error: You cannot enter an interactive shell on multiple containers concurrently using '*' wildcards.{RESET}")
        sys.exit(1)
        
    agent = get_container_config(settings, agent_name)
    if not agent:
        print(f"{RED}❌ Error: Agent '{agent_name}' is not defined in containers_settings.json.{RESET}")
        sys.exit(1)

    container_name = resolve_container_name(agent_name)
    if not is_container_running(container_name):
        print(f"{YELLOW}⚠️  Container '{container_name}' is not running. Automatically starting...{RESET}")
        start_agent(agent)

    print(f"{GREEN}📂 Slipping down into container sandbox '{container_name}' as unprivileged agent...{RESET}\n")
    subprocess.run(["docker", "exec", "-it", container_name, "bash"])

def do_status():
    settings = load_settings()
    
    groupings = {}
    grp_file = get_groupings_path()
    if grp_file:
        try:
            with open(grp_file, "r") as f:
                groupings = json.load(f).get("container_groupings", {})
        except Exception:
            pass
            
    container_to_group = {}
    for grp, info in groupings.items():
        for c in info.get("containers", []):
            container_to_group[c] = grp
            
    grouped_containers = {}
    containers = settings.get("containers") or settings.get("agents", [])
    for agent in containers:
        name = agent.get("name")
        grp = container_to_group.get(name, "unassigned")
        if grp not in grouped_containers:
            grouped_containers[grp] = []
        grouped_containers[grp].append(agent)
        
    print_header("MULTI-CONTAINER SYSTEM DASHBOARD")
    
    for grp, grp_containers in grouped_containers.items():
        grp_label = grp.upper()
        print(f"{BOLD}{BLUE}📦 [ {grp_label} GROUP ]{RESET}")
        print(f"{BOLD}{'CONTAINER':<15} | {'SYSTEM NAME':<20} | {'STATUS':<12} | {'NET':<9} | {'SUDO':<5} | {'LIMITS':<10}{RESET}")
        print("-" * 82)
        
        for agent in grp_containers:
            name = agent.get("name")
            container_name = resolve_container_name(name)
            
            if is_container_running(container_name):
                raw_status = "RUNNING"
                status = f"{GREEN}{raw_status:<12}{RESET}"
            elif is_container_exists(container_name):
                raw_status = "STOPPED"
                status = f"{YELLOW}{raw_status:<12}{RESET}"
            else:
                raw_status = "NOT CREATED"
                status = f"{RED}{raw_status:<12}{RESET}"
                
            allow_host, allow_external, allow_containers, _ = parse_network_settings(agent)

            security_config = agent.get("security", {})
            allow_sudo = security_config.get("allow_sudo", agent.get("toggle_sudo", False))
            
            if not allow_host or (not allow_external and not allow_containers):
                raw_net = "OFF"
                net = f"{RED}{raw_net:<9}{RESET}"
            elif allow_host and allow_external == ["*"] and allow_containers == ["*"]:
                raw_net = "ON"
                net = f"{GREEN}{raw_net:<9}{RESET}"
            elif allow_host and not allow_external and allow_containers == ["*"]:
                raw_net = "LOCAL"
                net = f"{BLUE}{raw_net:<9}{RESET}"
            elif allow_host and not allow_external and (allow_containers and allow_containers != ["*"]):
                raw_net = "CONTAINER"
                net = f"{CYAN}{raw_net:<9}{RESET}"
            else:
                raw_net = "PROXY"
                net = f"{YELLOW}{raw_net:<9}{RESET}"
                
            raw_sudo = "ON" if allow_sudo else "OFF"
            sudo_color = GREEN if allow_sudo else RED
            sudo = f"{sudo_color}{raw_sudo:<5}{RESET}"
            
            cpu = agent.get("cpu_limit", "unlimited")
            mem = agent.get("memory_limit", "unlimited")
            limits = f"C:{cpu} M:{mem}"
            
            print(f"{BOLD}{name:<15}{RESET} | {container_name:<20} | {status} | {net} | {sudo} | {limits:<10}")
        print()

def do_edit():
    target = SETTINGS_FILE if os.path.exists(SETTINGS_FILE) else SETTINGS_EXAMPLE_FILE
    editor = os.environ.get("EDITOR")
    if not editor:
        if shutil.which("code"):
            editor = "code"
        elif shutil.which("nano"):
            editor = "nano"
        else:
            editor = "vi"
    print(f"{GREEN}📝 Opening {os.path.basename(target)} in {editor}...{RESET}")
    subprocess.run([editor, target])

def do_logs(agent):
    name = agent.get("name")
    container_name = resolve_container_name(name)
    print(f"{GREEN}📋 Streaming logs for container '{container_name}' (Ctrl+C to exit)...{RESET}")
    try:
        subprocess.run(["docker", "logs", "-f", container_name])
    except KeyboardInterrupt:
        print(f"\n{YELLOW}🛑 Stopped streaming logs.{RESET}")

def do_explain(settings, target_containers):
    print_header("RESOLVED LIFECYCLE PLANS")
    for name in target_containers:
        agent = get_container_config(settings, name)
        if not agent:
            print(f"{RED}❌ Error: Container '{name}' is not defined.{RESET}")
            continue
            
        errors = lifecycle_action_validator.validate_agent_lifecycle(agent)
        
        print(f"\n{BOLD}{BLUE}📦 Container: {name}{RESET}")
        if errors:
            print(f"  {RED}⚠️  Validation Status: INVALID ({len(errors)} errors found){RESET}")
            for err in errors:
                print(f"    ❌ {err}")
        else:
            print(f"  {GREEN}✅ Validation Status: VALID{RESET}")
            
        lifecycle = lifecycle_action_validator.normalize_lifecycle(agent)
        
        phases = {
            "host_prepare": "⚙️  Host Prepare (Runs on host before boot)",
            "image_prepare": "🛠️  Image Prepare (Runs on builder during build)",
            "container_startup": "🔄 Container Startup (Runs inside container on start)",
            "healthcheck": "🔍 Healthcheck (Runs on host after boot)",
            "shutdown": "🛑 Shutdown (Runs inside/outside container before stop)"
        }
        
        for phase_key, phase_title in phases.items():
            content = lifecycle.get(phase_key)
            if not content:
                print(f"  {BOLD}{phase_title}{RESET}: {YELLOW}[None]{RESET}")
                continue
                
            print(f"  {BOLD}{phase_title}{RESET}:")
            
            if phase_key == "container_startup":
                behavior = content.get("behavior", "NEVER")
                print(f"    Behavior Policy: {BOLD}{YELLOW}{behavior}{RESET}")
                steps = content.get("steps", [])
                if not steps:
                    print(f"    Steps: {YELLOW}[None]{RESET}")
                else:
                    for i, step in enumerate(steps):
                        action_name = step.get("@action")
                        print(f"      [{i}] {GREEN}@action: {action_name}{RESET}")
                        for k, v in step.items():
                            if k != "@action":
                                print(f"          {k}: {v}")
            else:
                for i, step in enumerate(content):
                    action_name = step.get("@action")
                    print(f"    [{i}] {GREEN}@action: {action_name}{RESET}")
                    for k, v in step.items():
                        if k != "@action":
                            print(f"        {k}: {v}")
    print()

def resolve_targets(args, settings):
    if not args:
        default_c = get_default_container()
        return [default_c], False

    first_arg = args[0].lower()
    if first_arg in ["g", "group"]:
        if len(args) < 2:
            print(f"{RED}❌ Error: Grouping name(s) not specified. Usage: sandbox <cmd> g <group_name> or g {{group1,group2}}{RESET}")
            sys.exit(1)
        
        group_expr = " ".join(args[1:]).strip()
        if group_expr.startswith("{") and group_expr.endswith("}"):
            group_expr = group_expr[1:-1]
            
        groups = [g.strip() for g in group_expr.split(",") if g.strip()]
        
        groupings = {}
        grp_file = get_groupings_path()
        if grp_file:
            try:
                with open(grp_file, "r") as f:
                    groupings = json.load(f).get("container_groupings", {})
            except Exception:
                pass
                
        target_containers = []
        containers = settings.get("containers") or settings.get("agents", [])
        for g in groups:
            if g in groupings:
                target_containers.extend(groupings[g].get("containers", []))
            elif any(c.get("name") == g for c in containers):
                target_containers.append(g)
            else:
                print(f"{YELLOW}⚠️  Warning: '{g}' is neither a defined grouping nor a container in settings.{RESET}")
                
        if not target_containers:
            print(f"{RED}❌ Error: No valid containers resolved for specified groupings.{RESET}")
            sys.exit(1)
            
        seen = set()
        deduped = [x for x in target_containers if not (x in seen or seen.add(x))]
        return deduped, True

    if args[0] == "*":
        containers = settings.get("containers") or settings.get("agents", [])
        target_containers = [c.get("name") for c in containers]
        return target_containers, True

    combined_expr = " ".join(args).strip()
    if len(args) > 1 or "," in combined_expr or combined_expr.startswith("{"):
        if combined_expr.startswith("{") and combined_expr.endswith("}"):
            combined_expr = combined_expr[1:-1]
            
        if "," in combined_expr:
            targets = [c.strip() for c in combined_expr.split(",") if c.strip()]
        else:
            targets = [c.strip() for c in combined_expr.split() if c.strip()]
            
        return targets, True

    return [args[0]], False

def main():
    if len(sys.argv) < 2:
        pass
    else:
        cmd = sys.argv[1].lower()
        
        if cmd in ["status", "ps", "dashboard"]:
            do_status()
            sys.exit(0)
        elif cmd == "edit":
            do_edit()
            sys.exit(0)
        elif cmd in ["help", "-h", "--help"]:
            pass
        else:
            settings = load_settings()
            target_containers, is_bulk = resolve_targets(sys.argv[2:], settings)
            
            if cmd in ["start", "up", "rebuild"]:
                errors = lifecycle_action_validator.validate_all_settings(settings)
                if errors:
                    print_header("LIFECYCLE VALIDATION FAILED")
                    for agent_name, agent_errors in errors.items():
                        print(f"{BOLD}{YELLOW}Agent '{agent_name}':{RESET}")
                        for err in agent_errors:
                            print(f"  ❌ {err}")
                    print(f"\n{RED}❌ Error: Sandbox boot aborted due to validation errors. Please correct 'containers_settings.json'.{RESET}\n")
                    sys.exit(1)

            if cmd in ["start", "up", "stop", "down", "rebuild", "logs", "explain"]:
                if cmd in ["start", "up", "rebuild"]:
                    do_build()
                    
                if cmd == "explain":
                    do_explain(settings, target_containers)
                    sys.exit(0)
                    
                for target_name in target_containers:
                    agent = get_container_config(settings, target_name)
                    if not agent:
                        print(f"{RED}❌ Error: Container '{target_name}' is not defined in containers_settings.json.{RESET}")
                        continue
                        
                    if cmd in ["start", "up"]:
                        start_agent(agent)
                    elif cmd in ["stop", "down"]:
                        stop_agent(agent)
                    elif cmd == "rebuild":
                        stop_agent(agent)
                        start_agent(agent)
                    elif cmd == "logs":
                        do_logs(agent)
                sys.exit(0)
                
            elif cmd in ["enter", "shell"]:
                if len(target_containers) > 1 or is_bulk:
                    print(f"{RED}❌ Error: You cannot enter an interactive shell on multiple containers concurrently.{RESET}")
                    sys.exit(1)
                do_enter(target_containers[0])
                sys.exit(0)
            else:
                print(f"{RED}❌ Unknown command: '{cmd}'{RESET}")

    print_header("SANDBOX MANAGEMENT COMMANDS")
    print(f"Usage: {BOLD}sandbox <command> [target_expression]{RESET}\n")
    print("Target Expressions can be:")
    print(f"  {BOLD}name{RESET}                   A single container name (e.g. 'dev-sandbox')")
    print(f"  {BOLD}\\* / '*'{RESET}              All configured containers (e.g. '\\*' or '*')")
    print(f"  {BOLD}g <group>{RESET}             All containers in a grouping (e.g. 'g development')")
    print(f"  {BOLD}g {{grp1,grp2}}{RESET}      Containers in multiple groupings (e.g. 'g {{development,ai}}')")
    print(f"  {BOLD}{{c1,c2}}{RESET}             A list of container names (e.g. '{{dev-sandbox,ai-service}}')\n")
    print("Available Commands:")
    print(f"  {BOLD}status{RESET}               Show status table of all defined sandboxes")
    print(f"  {BOLD}start [target]{RESET}       Start matched system container(s)")
    print(f"  {BOLD}stop [target]{RESET}        Stop matched system container(s)")
    print(f"  {BOLD}enter [name]{RESET}         Log into a specific container's interactive shell")
    print(f"  {BOLD}rebuild [target]{RESET}     Stop, rebuild Docker images, and restart container(s)")
    print(f"  {BOLD}logs [target]{RESET}        Stream live outputs for matched container(s)")
    print(f"  {BOLD}explain [target]{RESET}     Visualize the resolved lifecycle plan for container(s)")
    print(f"  {BOLD}edit{RESET}                 Open the containers_settings.json configuration file")
    print(f"  {BOLD}help{RESET}                 Print this help reference sheet\n")

if __name__ == "__main__":
    main()
