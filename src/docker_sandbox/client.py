"""Main Sandbox orchestrator and SDK client for Docker Sandbox Protocol."""
import json
import os
import shutil
import socket
import subprocess
import sys
from typing import Any, Optional
from urllib.parse import urlparse

from docker_sandbox.config import SandboxConfig, expand_path
from docker_sandbox.exceptions import (
    ConfigError,
    ConfiguredCommandError,
    DockerUnavailableError,
    LifecycleError,
    LifecycleExecutionError,
    SandboxError,
    TargetNotFoundError,
)
from docker_sandbox.lifecycle import (
    normalize_lifecycle,
    validate_agent_lifecycle,
    validate_all_settings,
)
from docker_sandbox.models import (
    ActionResult,
    CommandInvocation,
    ContainerStatus,
    LifecycleValidationResult,
    StatusReport,
)


class Sandbox:
    """Enterprise container orchestration client for developer and agent sandboxes."""

    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()

    # -------------------------------------------------------------------------
    # System & Docker Inspection
    # -------------------------------------------------------------------------

    def get_docker_unavailable_reason(self) -> Optional[str]:
        """Return a user-facing reason if the Docker daemon cannot be queried."""
        try:
            res = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                env=self.config.docker_environment(),
            )
        except FileNotFoundError:
            return "Docker CLI is not installed or is not available in PATH."
        except OSError as exc:
            return f"Unable to execute the Docker CLI: {exc}"

        if res.returncode == 0:
            return None

        detail = res.stderr.strip() or res.stdout.strip()
        return detail or f"Docker exited with status {res.returncode}."

    def is_docker_available(self) -> bool:
        return self.get_docker_unavailable_reason() is None

    def is_container_running(self, container_name: str) -> bool:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            capture_output=True,
            text=True,
            env=self.config.docker_environment(),
        )
        return res.returncode == 0 and res.stdout.strip() == "true"

    def is_container_exists(self, container_name: str) -> bool:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", container_name],
            capture_output=True,
            text=True,
            env=self.config.docker_environment(),
        )
        return res.returncode == 0

    def get_container_ip(self, container_name: str) -> Optional[str]:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_name],
            capture_output=True,
            text=True,
            env=self.config.docker_environment(),
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
        return None

    # -------------------------------------------------------------------------
    # Network, Proxy, and Security Helpers
    # -------------------------------------------------------------------------

    def parse_network_settings(self, agent: dict[str, Any]) -> tuple[bool, list, list, list]:
        ports_to_bind = []
        network_config = agent.get("network", {})

        if isinstance(network_config, dict) and (
            "host_access" in network_config
            or "external_access" in network_config
            or "container_access" in network_config
        ):
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

    @staticmethod
    def append_runtime_security_options(cmd: list[str], security_config: dict[str, Any]) -> list[str]:
        """Append declarative Docker runtime hardening options to a run command."""
        run_as_user = security_config.get("run_as_user")
        if run_as_user is not None and str(run_as_user).strip():
            cmd += ["--user", str(run_as_user)]

        cap_drop = security_config.get("cap_drop", [])
        if isinstance(cap_drop, str):
            cap_drop = [cap_drop]
        for capability in cap_drop:
            if str(capability).strip():
                cmd += ["--cap-drop", str(capability)]

        if security_config.get("no_new_privileges", False):
            cmd += ["--security-opt", "no-new-privileges=true"]

        return cmd

    def register_proxy_rules(self, container_name: str, allowed_domains: list[str], allowed_containers: list[str] = None) -> None:
        container_ip = self.get_container_ip(container_name)
        if not container_ip:
            return

        rules = {}
        if os.path.exists(self.config.proxy_rules_file):
            try:
                with open(self.config.proxy_rules_file, "r") as f:
                    rules = json.load(f)
            except Exception:
                pass

        rule_entry = {"domains": allowed_domains, "name": container_name}
        if allowed_containers:
            rule_entry["containers"] = allowed_containers

        rules[container_ip] = rule_entry

        if "container_ips" not in rules:
            rules["container_ips"] = {}
        rules["container_ips"][container_ip] = container_name

        with open(self.config.proxy_rules_file, "w") as f:
            json.dump(rules, f, indent=2)

    def unregister_proxy_rules(self, container_name: str) -> None:
        container_ip = self.get_container_ip(container_name)
        if not container_ip or not os.path.exists(self.config.proxy_rules_file):
            return
        try:
            with open(self.config.proxy_rules_file, "r") as f:
                rules = json.load(f)
            if container_ip in rules:
                del rules[container_ip]
            if "container_ips" in rules and container_ip in rules["container_ips"]:
                del rules["container_ips"][container_ip]
            with open(self.config.proxy_rules_file, "w") as f:
                json.dump(rules, f, indent=2)
        except Exception:
            pass

    def register_container_ip(self, container_name: str) -> None:
        container_ip = self.get_container_ip(container_name)
        if container_ip:
            rules = {}
            if os.path.exists(self.config.proxy_rules_file):
                try:
                    with open(self.config.proxy_rules_file, "r") as f:
                        rules = json.load(f)
                except Exception:
                    pass
            if "container_ips" not in rules:
                rules["container_ips"] = {}

            rules["container_ips"][container_ip] = container_name
            with open(self.config.proxy_rules_file, "w") as f:
                json.dump(rules, f, indent=2)

    def ensure_proxy_running(self) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", 8888))
            s.close()
            proxy_path = os.path.join(self.config.config_dir, "proxy.py")
            if os.path.exists(proxy_path):
                subprocess.Popen(
                    [sys.executable, proxy_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    env=os.environ.copy(),
                )
                return True
        except socket.error:
            return False
        return False

    # -------------------------------------------------------------------------
    # Lifecycle Execution
    # -------------------------------------------------------------------------

    def execute_lifecycle_step(self, phase: str, step: dict[str, Any], container_name: Optional[str] = None) -> tuple[int, str]:
        registry = self.config.load_registry()
        action_name = step.get("@action")
        action_meta = registry["actions"][action_name]
        script_name = action_meta["script"]
        script_path = os.path.join(self.config.scripts_dir, script_name)

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
                str_val = expand_path(str(val)) if "path" in key else str(val)
                cmd.extend([f"--{key}", str_val])

        if action_meta.get("runs_on") == "container" and container_name:
            cmd.extend(["--container", container_name])

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise LifecycleExecutionError(phase, step, res.returncode, res.stderr)
        return res.returncode, res.stdout.strip()

    def run_healthchecks(self, agent: dict[str, Any], container_name: str) -> None:
        lifecycle = normalize_lifecycle(agent)
        healthcheck = lifecycle.get("healthcheck", [])
        for step in healthcheck:
            self.execute_lifecycle_step("healthcheck", step, container_name)

    # -------------------------------------------------------------------------
    # Presets & Builds
    # -------------------------------------------------------------------------

    @staticmethod
    def parse_version(v_str: str) -> list:
        v_str = v_str.strip().lower()
        if v_str.startswith("v"):
            v_str = v_str[1:]
        parts = []
        for part in v_str.split("."):
            try:
                parts.append(int(part))
            except ValueError:
                parts.append(part)
        return parts

    @staticmethod
    def compare_versions(v1: str, v2: str) -> int:
        p1 = Sandbox.parse_version(v1)
        p2 = Sandbox.parse_version(v2)
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

    @staticmethod
    def match_version(version: str, specifier: str) -> bool:
        specifier = specifier.strip()
        if not specifier or specifier in ["*", "default"]:
            return True

        ops = [">=", "<=", "==", ">", "<", "~="]
        op = None
        val = specifier
        for candidate in ops:
            if specifier.startswith(candidate):
                op = candidate
                val = specifier[len(candidate):].strip()
                break

        if op is None or op == "==":
            return Sandbox.compare_versions(version, val) == 0
        elif op == ">":
            return Sandbox.compare_versions(version, val) > 0
        elif op == "<":
            return Sandbox.compare_versions(version, val) < 0
        elif op == ">=":
            return Sandbox.compare_versions(version, val) >= 0
        elif op == "<=":
            return Sandbox.compare_versions(version, val) <= 0
        elif op == "~=":
            p_ver = Sandbox.parse_version(version)
            p_val = Sandbox.parse_version(val)
            if len(p_val) == 1:
                return p_ver[0] == p_val[0] and Sandbox.compare_versions(version, val) >= 0
            elif len(p_val) >= 2:
                return p_ver[0] == p_val[0] and p_ver[1] == p_val[1] and Sandbox.compare_versions(version, val) >= 0
        return False

    def resolve_requirements(self, requirements: list[str]) -> tuple[list[str], dict[str, str]]:
        presets = self.config.load_presets()
        if not presets:
            return [], {}

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
                continue

            preset_info = presets[name]
            versions_dict = preset_info.get("versions", {})
            default_version = preset_info.get("default_version", "")
            is_default_or_any = specifier in ["", "*", "default"]

            if is_default_or_any:
                if default_version in versions_dict:
                    selected_version = default_version
                elif versions_dict:
                    sorted_vers = sorted(versions_dict.keys(), key=lambda x: Sandbox.parse_version(x))
                    selected_version = sorted_vers[-1]
                else:
                    continue
            else:
                matching_versions = [v for v in versions_dict.keys() if Sandbox.match_version(v, specifier)]
                if not matching_versions:
                    if default_version in versions_dict:
                        selected_version = default_version
                    elif versions_dict:
                        sorted_vers = sorted(versions_dict.keys(), key=lambda x: Sandbox.parse_version(x))
                        selected_version = sorted_vers[-1]
                    else:
                        continue
                else:
                    sorted_matching = sorted(matching_versions, key=lambda x: Sandbox.parse_version(x))
                    selected_version = sorted_matching[-1]

            version_details = versions_dict[selected_version]
            cmd = version_details.get("command")
            if cmd:
                install_commands.append(cmd)
            env = version_details.get("env", {})
            env_vars.update(env)

        return install_commands, env_vars

    def build_custom_image(self, agent_name: str, requirements: list[str]) -> str:
        custom_image_name = f"{self.config.image_name}-{agent_name}"
        install_commands, env_vars = self.resolve_requirements(requirements)
        if not install_commands and not env_vars:
            return self.config.image_name

        dockerfile_lines = [
            f"FROM {self.config.image_name}",
            "USER root",
            "ENV DEBIAN_FRONTEND=noninteractive",
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
            return custom_image_name
        return self.config.image_name

    def build_base_image(self) -> ActionResult:
        if not os.path.exists(self.config.dockerfile):
            raise ConfigError(f"Dockerfile not found at {self.config.dockerfile}")
        res = subprocess.run(["docker", "build", "-t", self.config.image_name, self.config.config_dir])
        if res.returncode != 0:
            return ActionResult(
                target="base",
                container_name=self.config.image_name,
                action="build",
                success=False,
                message="Base Docker image build failed",
            )
        return ActionResult(
            target="base",
            container_name=self.config.image_name,
            action="build",
            success=True,
            message=f"Image '{self.config.image_name}' built successfully",
        )

    # -------------------------------------------------------------------------
    # Startup Scripts Setup
    # -------------------------------------------------------------------------

    def setup_and_run_startup(self, agent: dict[str, Any], container_name: str) -> None:
        subprocess.run(["docker", "exec", "-u", "root", container_name, "touch", "/var/log/sandbox_startup.log"])
        subprocess.run(["docker", "exec", "-u", "root", container_name, "chmod", "666", "/var/log/sandbox_startup.log"])
        subprocess.run(
            ["docker", "exec", "-u", "root", container_name, "sh", "-c", "echo \"[$(date '+%Y-%m-%d %H:%M:%S')] Container booted / started\" >> /var/log/sandbox_startup.log"]
        )

        lifecycle = normalize_lifecycle(agent)
        container_startup = lifecycle.get("container_startup", {})
        behavior = container_startup.get("behavior", "NEVER").upper()
        steps = container_startup.get("steps", [])

        commands = []
        for step in steps:
            if step.get("@action") == "shell":
                commands.append(step.get("command"))

        behavior_content = f"Startup Behavior: {behavior}\n"
        subprocess.run(
            ["docker", "exec", "-u", "root", "-i", container_name, "sh", "-c", "cat > /etc/sandbox_behavior"],
            input=behavior_content,
            text=True,
        )

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
            subprocess.run(exec_cmd)
        elif behavior == "ONCE":
            check_res = subprocess.run(["docker", "exec", container_name, "test", "-f", "/var/lib/sandbox_startup_done"])
            if check_res.returncode != 0:
                subprocess.run(exec_cmd)
                subprocess.run(["docker", "exec", "-u", "root", container_name, "touch", "/var/lib/sandbox_startup_done"])
            else:
                log_msg = "[$(date '+%Y-%m-%d %H:%M:%S')] Startup script skipped because it already executed once (ONCE behavior)"
                subprocess.run(["docker", "exec", container_name, "sh", "-c", f"echo \"{log_msg}\" >> /var/log/sandbox_startup.log"])
        else:
            log_msg = "[$(date '+%Y-%m-%d %H:%M:%S')] Startup script skipped (NEVER behavior)"
            subprocess.run(["docker", "exec", container_name, "sh", "-c", f"echo \"{log_msg}\" >> /var/log/sandbox_startup.log"])

    # -------------------------------------------------------------------------
    # Core Operations: start, stop, restart, status, explain, in
    # -------------------------------------------------------------------------

    def status(self) -> StatusReport:
        """Collect status for all declared containers."""
        docker_error = self.get_docker_unavailable_reason()
        if docker_error:
            return StatusReport(docker_available=False, docker_error=docker_error, groups={})

        settings, _ = self.config.load_settings()
        groupings = self.config.load_groupings()

        container_to_group = {}
        for grp, info in groupings.items():
            for c in info.get("containers", []):
                container_to_group[c] = grp

        grouped_containers: dict[str, list[ContainerStatus]] = {}
        containers = settings.get("containers") or settings.get("agents", [])

        for agent in containers:
            name = agent.get("name")
            grp = container_to_group.get(name, "unassigned")
            container_name = self.config.resolve_container_name(name)

            is_running = self.is_container_running(container_name)
            exists = self.is_container_exists(container_name)

            if is_running:
                raw_status = "RUNNING"
            elif exists:
                raw_status = "STOPPED"
            else:
                raw_status = "NOT CREATED"

            allow_host, allow_external, allow_containers, _ = self.parse_network_settings(agent)
            security_config = agent.get("security", {})
            allow_sudo = security_config.get("allow_sudo", agent.get("toggle_sudo", False))

            if not allow_host or (not allow_external and not allow_containers):
                net = "OFF"
            elif allow_host and allow_external == ["*"] and allow_containers == ["*"]:
                net = "ON"
            elif allow_host and not allow_external and allow_containers == ["*"]:
                net = "LOCAL"
            elif allow_host and not allow_external and (allow_containers and allow_containers != ["*"]):
                net = "CONTAINER"
            else:
                net = "PROXY"

            cpu = str(agent.get("cpu_limit", "unlimited"))
            mem = str(agent.get("memory_limit", "unlimited"))

            status_item = ContainerStatus(
                name=name,
                system_name=container_name,
                group=grp,
                raw_status=raw_status,
                network_mode=net,
                sudo_allowed=allow_sudo,
                cpu_limit=cpu,
                memory_limit=mem,
                is_running=is_running,
                exists=exists,
                raw_config=agent,
            )

            if grp not in grouped_containers:
                grouped_containers[grp] = []
            grouped_containers[grp].append(status_item)

        return StatusReport(
            docker_available=True,
            docker_error=None,
            groups=grouped_containers,
        )

    def start_container(self, agent: dict[str, Any]) -> ActionResult:
        """Start a single agent or Compose stack."""
        name = agent.get("name")
        container_name = self.config.resolve_container_name(name)

        if not agent.get("enabled", True):
            return ActionResult(
                target=name,
                container_name=container_name,
                action="start",
                success=True,
                skipped=True,
                message=f"Agent '{name}' is disabled in settings.",
            )

        # Host prepare
        if not self.is_container_running(container_name):
            lifecycle = normalize_lifecycle(agent)
            host_prepare = lifecycle.get("host_prepare", [])
            for step in host_prepare:
                self.execute_lifecycle_step("host_prepare", step, container_name)

        # Compose delegation
        compose_path = agent.get("compose_path")
        if compose_path:
            compose_path = expand_path(compose_path)
            if not os.path.exists(compose_path):
                return ActionResult(
                    target=name,
                    container_name=container_name,
                    action="start",
                    success=False,
                    message=f"Compose file '{compose_path}' not found.",
                )

            if self.is_container_running(container_name):
                return ActionResult(
                    target=name,
                    container_name=container_name,
                    action="start",
                    success=True,
                    skipped=True,
                    message=f"Container '{container_name}' is already running via Compose.",
                )

            compose_env_files = self.config.get_compose_env_files(agent)
            compose_environment = self.config.get_compose_environment(agent)
            compose_bin = self.config.get_compose_bin()

            compose_cmd = [compose_bin]
            for compose_env_file in compose_env_files:
                compose_cmd += ["--env-file", compose_env_file]

            res = subprocess.run([*compose_cmd, "-f", compose_path, "up", "-d"], env=compose_environment)
            if res.returncode == 0:
                self.run_healthchecks(agent, container_name)
                return ActionResult(
                    target=name,
                    container_name=container_name,
                    action="start",
                    success=True,
                    message="Docker Compose stack successfully launched.",
                )
            return ActionResult(
                target=name,
                container_name=container_name,
                action="start",
                success=False,
                message="Failed to start docker-compose stack.",
            )

        # Standard container
        if self.is_container_running(container_name):
            return ActionResult(
                target=name,
                container_name=container_name,
                action="start",
                success=True,
                skipped=True,
                message=f"Agent '{name}' is already running in container '{container_name}'.",
            )

        if self.is_container_exists(container_name):
            subprocess.run(["docker", "start", container_name])
            allow_host, allow_external, allow_containers, _ = self.parse_network_settings(agent)
            if allow_host and (allow_external != ["*"] or allow_containers != ["*"]):
                self.register_proxy_rules(container_name, allow_external, allow_containers)
                self.ensure_proxy_running()
                subprocess.run(["docker", "exec", container_name, "ip", "route", "del", "default"], capture_output=True)
            else:
                self.register_container_ip(container_name)

            if not agent.get("image"):
                self.setup_and_run_startup(agent, container_name)
            self.run_healthchecks(agent, container_name)
            return ActionResult(
                target=name,
                container_name=container_name,
                action="start",
                success=True,
                message=f"Container '{container_name}' started successfully.",
            )

        custom_image = agent.get("image")
        if custom_image:
            active_image = custom_image
        else:
            requirements = agent.get("requirements", [])
            active_image = self.config.image_name
            if requirements:
                self.build_base_image()
                active_image = self.build_custom_image(name, requirements)

        # Build workspace/scratch paths
        for path_key in ["workspace_path", "scratch_path"]:
            raw_path = agent.get(path_key)
            if raw_path:
                path = expand_path(raw_path)
                if not os.path.exists(path):
                    os.makedirs(path, exist_ok=True)
                    try:
                        shutil.chown(path, user=1001, group=1001)
                    except Exception:
                        try:
                            os.chmod(path, 0o777)
                        except Exception:
                            pass

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--restart", "unless-stopped",
        ]

        volumes = agent.get("volumes")
        if volumes is not None:
            for vol in volumes:
                cmd += ["-v", vol]
        else:
            agent_home = os.environ.get("SANDBOX_AGENT_HOME", "/home/agentic")
            if os.path.exists(agent_home):
                cmd += ["-v", f"{agent_home}:/home/agent"]
            if agent.get("workspace_path"):
                cmd += ["-v", f"{expand_path(agent.get('workspace_path'))}:/workspace"]
            if agent.get("scratch_path"):
                cmd += ["-v", f"{expand_path(agent.get('scratch_path'))}:/scratch"]

        if agent.get("cpu_limit"):
            cmd += ["--cpus", str(agent.get("cpu_limit"))]
        if agent.get("memory_limit"):
            cmd += ["--memory", str(agent.get("memory_limit"))]

        allow_host, allow_external, allow_containers, ports = self.parse_network_settings(agent)

        if allow_containers:
            try:
                inspect_res = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, check=True)
                container_ids = inspect_res.stdout.strip().split()
                if container_ids:
                    inspect_info = subprocess.run(["docker", "inspect"] + container_ids, capture_output=True, text=True, check=True)
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
            except Exception:
                pass

        for port in ports:
            cmd += ["-p", port]

        security_config = agent.get("security", {})
        allow_sudo = security_config.get("allow_sudo", agent.get("toggle_sudo", False))
        allow_google_auth = security_config.get("allow_google_auth", agent.get("toggle_google_auth", False))

        self.append_runtime_security_options(cmd, security_config)

        if not allow_host and not allow_external:
            cmd += ["--network", "none"]
        elif allow_host and (allow_external != ["*"] or allow_containers != ["*"]):
            cmd += ["--cap-add", "NET_ADMIN"]
            no_proxy_val = (
                "localhost,127.0.0.1,172.17.0.1,172.17.0.0/16,172.18.0.0/16,172.19.0.0/16,172.20.0.0/16"
                if allow_containers == ["*"] else "localhost,127.0.0.1,172.17.0.1"
            )
            cmd += [
                "-e", "http_proxy=http://172.17.0.1:8888",
                "-e", "https_proxy=http://172.17.0.1:8888",
                "-e", "HTTP_PROXY=http://172.17.0.1:8888",
                "-e", "HTTPS_PROXY=http://172.17.0.1:8888",
                "-e", f"no_proxy={no_proxy_val}",
            ]

        env_vars = agent.get("environment", {})
        if isinstance(env_vars, dict):
            for k, v in env_vars.items():
                cmd += ["-e", f"{k}={v}"]
        elif isinstance(env_vars, list):
            for env_item in env_vars:
                cmd += ["-e", env_item]

        if not allow_sudo:
            cmd += ["-v", "/dev/null:/usr/bin/sudo:ro"]

        if allow_google_auth:
            otp_file = "/var/lib/google-authenticator/agentic"
            if os.path.exists(otp_file):
                cmd += ["-v", f"{otp_file}:/etc/security/google-authenticator/agent:ro"]

        cmd += [active_image]

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
            if allow_host and (allow_external != ["*"] or allow_containers != ["*"]):
                self.register_proxy_rules(container_name, allow_external, allow_containers)
                self.ensure_proxy_running()
                subprocess.run(["docker", "exec", container_name, "ip", "route", "del", "default"], capture_output=True)
            else:
                self.register_container_ip(container_name)

            if not custom_image:
                self.setup_and_run_startup(agent, container_name)
            self.run_healthchecks(agent, container_name)

            return ActionResult(
                target=name,
                container_name=container_name,
                action="start",
                success=True,
                message=f"Agent '{name}' successfully containerized and started.",
            )

        return ActionResult(
            target=name,
            container_name=container_name,
            action="start",
            success=False,
            message=f"Failed to start container for agent '{name}'.",
        )

    def stop_container(self, agent: dict[str, Any]) -> ActionResult:
        """Stop a single agent or Compose stack."""
        name = agent.get("name")
        container_name = self.config.resolve_container_name(name)

        compose_path = agent.get("compose_path")
        if compose_path:
            compose_path = expand_path(compose_path)
            if not os.path.exists(compose_path):
                return ActionResult(
                    target=name,
                    container_name=container_name,
                    action="stop",
                    success=False,
                    message=f"Compose file '{compose_path}' not found.",
                )

            compose_env_files = self.config.get_compose_env_files(agent)
            compose_environment = self.config.get_compose_environment(agent)
            compose_bin = self.config.get_compose_bin()

            compose_cmd = [compose_bin]
            for compose_env_file in compose_env_files:
                compose_cmd += ["--env-file", compose_env_file]

            res = subprocess.run([*compose_cmd, "-f", compose_path, "down"], env=compose_environment)
            if res.returncode == 0:
                return ActionResult(
                    target=name,
                    container_name=container_name,
                    action="stop",
                    success=True,
                    message="Docker Compose stack successfully stopped and removed.",
                )
            return ActionResult(
                target=name,
                container_name=container_name,
                action="stop",
                success=False,
                message="Failed to stop docker-compose stack.",
            )

        if not self.is_container_exists(container_name):
            return ActionResult(
                target=name,
                container_name=container_name,
                action="stop",
                success=True,
                skipped=True,
                message=f"Agent container '{container_name}' does not exist.",
            )

        if self.is_container_running(container_name):
            lifecycle = normalize_lifecycle(agent)
            shutdown_steps = lifecycle.get("shutdown", [])
            for step in shutdown_steps:
                self.execute_lifecycle_step("shutdown", step, container_name)

        self.unregister_proxy_rules(container_name)
        subprocess.run(["docker", "stop", container_name], capture_output=True)
        subprocess.run(["docker", "rm", container_name], capture_output=True)

        return ActionResult(
            target=name,
            container_name=container_name,
            action="stop",
            success=True,
            message=f"Container '{container_name}' stopped and removed.",
        )

    def start(self, targets: list[str] | str = "*") -> list[ActionResult]:
        """Start container(s) matching the target expression."""
        settings, _ = self.config.load_settings()
        resolved, _ = self.config.resolve_targets(targets, settings)
        results = []
        for name in resolved:
            agent = self.config.get_container_config(settings, name)
            if agent:
                results.append(self.start_container(agent))
            else:
                results.append(ActionResult(
                    target=name,
                    container_name=self.config.resolve_container_name(name),
                    action="start",
                    success=False,
                    message=f"Container '{name}' not found in settings.",
                ))
        return results

    def stop(self, targets: list[str] | str = "*") -> list[ActionResult]:
        """Stop container(s) matching the target expression."""
        settings, _ = self.config.load_settings()
        resolved, _ = self.config.resolve_targets(targets, settings)
        results = []
        for name in resolved:
            agent = self.config.get_container_config(settings, name)
            if agent:
                results.append(self.stop_container(agent))
            else:
                results.append(ActionResult(
                    target=name,
                    container_name=self.config.resolve_container_name(name),
                    action="stop",
                    success=False,
                    message=f"Container '{name}' not found in settings.",
                ))
        return results

    def restart(self, targets: list[str] | str = "*") -> list[ActionResult]:
        """Restart container(s) matching the target expression."""
        stop_results = self.stop(targets)
        start_results = self.start(targets)
        return stop_results + start_results

    def explain(self, targets: list[str] | str = "*") -> dict[str, LifecycleValidationResult]:
        """Validate and return lifecycle execution plans for targets."""
        settings, _ = self.config.load_settings()
        resolved, _ = self.config.resolve_targets(targets, settings)
        results = {}

        for name in resolved:
            agent = self.config.get_container_config(settings, name)
            if not agent:
                results[name] = LifecycleValidationResult(
                    container_name=name,
                    is_valid=False,
                    errors=[f"Container '{name}' is not defined."],
                    phases={},
                )
                continue

            errors = validate_agent_lifecycle(agent, config=self.config)
            lifecycle = normalize_lifecycle(agent)
            results[name] = LifecycleValidationResult(
                container_name=name,
                is_valid=len(errors) == 0,
                errors=errors,
                phases=lifecycle,
            )

        return results

    # -------------------------------------------------------------------------
    # In / Run Command Resolution
    # -------------------------------------------------------------------------

    @staticmethod
    def _configured_argv(value: Any, field_name: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or any(not isinstance(arg, str) or not arg for arg in value):
            raise ConfiguredCommandError(f"'{field_name}' must be a list of non-empty strings.")
        return list(value)

    @staticmethod
    def resolve_configured_invocation(
        agent: dict[str, Any],
        operation: str,
        selector: str,
        user_args: list[str],
    ) -> tuple[str, dict[str, Any], list[str]]:
        """Resolve a named or default open/run invocation without invoking a shell."""
        schema = {
            "open": ("targets", "target"),
            "run": ("functions", "function"),
        }
        if operation not in schema:
            raise ConfiguredCommandError(f"Unsupported container operation '{operation}'.")

        entries_key, reference_key = schema[operation]
        command_section = agent.get("commands", {}).get(operation)
        if not isinstance(command_section, dict):
            raise ConfiguredCommandError(
                f"Container '{agent.get('name', '<unnamed>')}' has no configured '{operation}' commands."
            )

        default_args = []
        is_default = selector == "."
        if is_default:
            default = command_section.get("default")
            if not isinstance(default, dict):
                raise ConfiguredCommandError(
                    f"Container '{agent.get('name', '<unnamed>')}' has no advanced '{operation}' default."
                )
            selected_name = default.get(reference_key)
            if not isinstance(selected_name, str) or not selected_name:
                raise ConfiguredCommandError(
                    f"'{operation}.default.{reference_key}' must name a configured {reference_key}."
                )
            default_args = Sandbox._configured_argv(default.get("args"), f"{operation}.default.args")
            allow_user_args = default.get("allow_user_args", False)
            if not isinstance(allow_user_args, bool):
                raise ConfiguredCommandError(
                    f"'{operation}.default.allow_user_args' must be true or false."
                )
        else:
            selected_name = selector
            allow_user_args = None

        entries = command_section.get(entries_key)
        if not isinstance(entries, dict):
            raise ConfiguredCommandError(f"'{operation}.{entries_key}' must be an object.")
        entry = entries.get(selected_name)
        if not isinstance(entry, dict):
            raise ConfiguredCommandError(
                f"Configured {reference_key} '{selected_name}' was not found for '{operation}'."
            )

        entry_allow_args = entry.get("allow_args", False)
        if not isinstance(entry_allow_args, bool):
            raise ConfiguredCommandError(
                f"'{operation}.{entries_key}.{selected_name}.allow_args' must be true or false."
            )

        caller_args_allowed = entry_allow_args and (allow_user_args if is_default else True)
        if user_args and not caller_args_allowed:
            invocation_name = "default invocation" if is_default else f"{reference_key} '{selected_name}'"
            raise ConfiguredCommandError(
                f"The {operation} {invocation_name} does not allow caller-supplied arguments."
            )

        entry_args = Sandbox._configured_argv(
            entry.get("args"), f"{operation}.{entries_key}.{selected_name}.args"
        )
        return selected_name, entry, entry_args + default_args + list(user_args)

    def in_cmd(
        self,
        container_name: str,
        operation: str = "run",
        selector: str = ".",
        user_args: Optional[list[str]] = None,
    ) -> CommandInvocation:
        """Resolve a configured container command invocation programmatically."""
        settings, _ = self.config.load_settings()
        agent = self.config.get_container_config(settings, container_name)
        if not agent:
            raise TargetNotFoundError(f"Container '{container_name}' is not defined.")

        user_args = user_args or []
        selected_name, entry, invocation_args = self.resolve_configured_invocation(
            agent, operation, selector, user_args
        )

        system_name = self.config.resolve_container_name(container_name)
        requires_running = operation == "run" or entry.get("requires_running", False)

        if operation == "run":
            argv = self._configured_argv(entry.get("argv"), f"run.functions.{selected_name}.argv")
            if not argv:
                raise ConfiguredCommandError(f"Configured function '{selected_name}' has no argv.")
            return CommandInvocation(
                container_name=container_name,
                system_name=system_name,
                command_type="run",
                target_name=selected_name,
                argv=argv + invocation_args,
                requires_running=requires_running,
            )

        # "open" operation
        target_type = entry.get("type")
        target_value = entry.get("value")
        url = None
        if target_type == "url":
            parsed = urlparse(target_value) if isinstance(target_value, str) else None
            if not parsed or parsed.scheme not in ["http", "https"] or not parsed.netloc:
                raise ConfiguredCommandError(f"Open target '{selected_name}' must use an http or https URL.")
            url = target_value
        elif target_type == "file":
            resolved_target = expand_path(target_value)
            if not os.path.exists(resolved_target):
                raise ConfiguredCommandError(f"Open target file does not exist: {resolved_target}")
            url = f"file://{resolved_target}"
        else:
            raise ConfiguredCommandError(f"Open target '{selected_name}' must have type 'url' or 'file'.")

        return CommandInvocation(
            container_name=container_name,
            system_name=system_name,
            command_type="open",
            target_name=selected_name,
            url=url,
            argv=invocation_args,
            requires_running=requires_running,
        )
