"""Terminal CLI user interface for Docker Sandbox Protocol."""
import os
import shutil
import subprocess
import sys
from typing import Optional

from docker_sandbox.client import Sandbox
from docker_sandbox.config import expand_path
from docker_sandbox.exceptions import (
    ConfigError,
    ConfiguredCommandError,
    TargetNotFoundError,
)
from docker_sandbox.lifecycle import validate_all_settings

# Terminal styling constants
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_header(title: str) -> None:
    print(f"\n{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{BLUE} 🛡️  {title} 🛡️{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}\n")


def do_status(sandbox: Sandbox) -> bool:
    print_header("MULTI-CONTAINER SYSTEM DASHBOARD")
    report = sandbox.status()

    if not report.docker_available:
        print(f"{RED}DOCKER UNAVAILABLE{RESET}")
        print(f"{RED}{report.docker_error}{RESET}")
        if report.docker_error and "permission denied" in report.docker_error.lower():
            print(
                f"{YELLOW}The current user cannot access the Docker daemon. "
                "Use an authorized Docker context, rootless Docker, or an explicitly elevated invocation."
                f"{RESET}"
            )
        return False

    for grp, grp_containers in report.groups.items():
        grp_label = grp.upper()
        print(f"{BOLD}{BLUE}📦 [ {grp_label} GROUP ]{RESET}")
        print(f"{BOLD}{'CONTAINER':<15} | {'SYSTEM NAME':<20} | {'STATUS':<12} | {'NET':<9} | {'SUDO':<5} | {'LIMITS':<10}{RESET}")
        print("-" * 82)

        for c in grp_containers:
            if c.raw_status == "RUNNING":
                status = f"{GREEN}{c.raw_status:<12}{RESET}"
            elif c.raw_status == "STOPPED":
                status = f"{YELLOW}{c.raw_status:<12}{RESET}"
            else:
                status = f"{RED}{c.raw_status:<12}{RESET}"

            if c.network_mode == "OFF":
                net = f"{RED}{c.network_mode:<9}{RESET}"
            elif c.network_mode == "ON":
                net = f"{GREEN}{c.network_mode:<9}{RESET}"
            elif c.network_mode == "LOCAL":
                net = f"{BLUE}{c.network_mode:<9}{RESET}"
            elif c.network_mode == "CONTAINER":
                net = f"{CYAN}{c.network_mode:<9}{RESET}"
            else:
                net = f"{YELLOW}{c.network_mode:<9}{RESET}"

            raw_sudo = "ON" if c.sudo_allowed else "OFF"
            sudo_color = GREEN if c.sudo_allowed else RED
            sudo = f"{sudo_color}{raw_sudo:<5}{RESET}"

            limits = f"C:{c.cpu_limit} M:{c.memory_limit}"
            print(f"{BOLD}{c.name:<15}{RESET} | {c.system_name:<20} | {status} | {net} | {sudo} | {limits:<10}")
        print()

    return True


def do_explain(sandbox: Sandbox, target_containers: list[str]) -> None:
    print_header("RESOLVED LIFECYCLE PLANS")
    settings, _ = sandbox.config.load_settings()

    for name in target_containers:
        agent = sandbox.config.get_container_config(settings, name)
        if not agent:
            print(f"{RED}❌ Error: Container '{name}' is not defined.{RESET}")
            continue

        validation = sandbox.explain(name).get(name)
        print(f"\n{BOLD}{BLUE}📦 Container: {name}{RESET}")

        if not validation or not validation.is_valid:
            error_count = len(validation.errors) if validation else 1
            print(f"  {RED}⚠️  Validation Status: INVALID ({error_count} errors found){RESET}")
            if validation:
                for err in validation.errors:
                    print(f"    ❌ {err}")
        else:
            print(f"  {GREEN}✅ Validation Status: VALID{RESET}")

        phases = {
            "host_prepare": "⚙️  Host Prepare (Runs on host before boot)",
            "image_prepare": "🛠️  Image Prepare (Runs on builder during build)",
            "container_startup": "🔄 Container Startup (Runs inside container on start)",
            "healthcheck": "🔍 Healthcheck (Runs on host after boot)",
            "shutdown": "🛑 Shutdown (Runs inside/outside container before stop)",
        }

        lifecycle = validation.phases if validation else {}
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


def print_configured_command_catalog(agent: dict) -> None:
    agent_name = agent.get("name", "<unnamed>")
    commands = agent.get("commands")
    print_header(f"CONFIGURED COMMANDS: {agent_name}")

    if not isinstance(commands, dict):
        print(f"{YELLOW}No configured commands are available for this container.{RESET}")
        return

    found_commands = False
    schema = {
        "open": ("targets", "target"),
        "run": ("functions", "function"),
    }
    for operation, (entries_key, reference_key) in schema.items():
        section = commands.get(operation)
        if not isinstance(section, dict):
            continue
        entries = section.get(entries_key)
        if not isinstance(entries, dict) or not entries:
            continue

        found_commands = True
        print(f"{BOLD}{operation.upper()} selectors{RESET}")

        default = section.get("default")
        if isinstance(default, dict):
            default_name = default.get(reference_key)
            if isinstance(default_name, str) and default_name:
                default_entry = entries.get(default_name, {})
                caller_args = bool(
                    default.get("allow_user_args", False)
                    and isinstance(default_entry, dict)
                    and default_entry.get("allow_args", False)
                )
                configured_args = default.get("args", [])
                configured_count = len(configured_args) if isinstance(configured_args, list) else 0
                details = [f"default → {default_name}"]
                if configured_count:
                    details.append(f"{configured_count} configured arg(s)")
                details.append(f"caller args: {'yes' if caller_args else 'no'}")
                print(f"  {BOLD}{'.':<14}{RESET} {'; '.join(details)}")

        for entry_name, entry in entries.items():
            if not isinstance(entry_name, str) or not isinstance(entry, dict):
                continue
            details = []
            if operation == "open":
                target_type = entry.get("type")
                if target_type in ["url", "file"]:
                    details.append(target_type)
            details.append(f"caller args: {'yes' if entry.get('allow_args', False) else 'no'}")
            description = entry.get("description")
            if isinstance(description, str) and description.strip():
                details.append(description.strip())
            print(f"  {BOLD}{entry_name:<14}{RESET} {'; '.join(details)}")

        print(f"  Call with: sandbox in c {agent_name} {operation} <selector> [args...]\n")

    if not found_commands:
        print(f"{YELLOW}No configured commands are available for this container.{RESET}")


def do_in(sandbox: Sandbox, args: list[str]) -> int:
    usage = "sandbox in c <container> [<open|run> <selector> [args...]]"
    if len(args) < 2:
        print(f"{RED}❌ Error: Missing configured-command arguments. Usage: {usage}{RESET}")
        return 1

    scope, agent_name, *request = args
    if scope.lower() not in ["c", "container"]:
        if scope.lower() in ["g", "group"]:
            print(f"{RED}❌ Error: Group-scoped configured commands are not supported yet.{RESET}")
        else:
            print(f"{RED}❌ Error: Unknown scope '{scope}'. Use 'c' for a container.{RESET}")
        return 1

    settings, _ = sandbox.config.load_settings()
    agent = sandbox.config.get_container_config(settings, agent_name)
    if not agent:
        print(f"{RED}❌ Error: Container '{agent_name}' is not defined in containers_settings.json.{RESET}")
        return 1

    if not request:
        print_configured_command_catalog(agent)
        return 0
    if len(request) < 2:
        print(f"{RED}❌ Error: Missing selector. Usage: {usage}{RESET}")
        return 1

    operation, selector, *user_args = request
    operation = operation.lower()

    try:
        inv = sandbox.in_cmd(agent_name, operation, selector, user_args)
    except ConfiguredCommandError as exc:
        print(f"{RED}❌ Error: {exc}{RESET}")
        return 1
    except TargetNotFoundError as exc:
        print(f"{RED}❌ Error: {exc}{RESET}")
        return 1

    if inv.requires_running:
        docker_error = sandbox.get_docker_unavailable_reason()
        if docker_error:
            print(f"{RED}❌ Docker unavailable: {docker_error}{RESET}")
            return 1
        if not sandbox.is_container_running(inv.system_name):
            print(f"{RED}❌ Error: Container '{inv.system_name}' is not running.{RESET}")
            return 1

    if inv.command_type == "run":
        try:
            return subprocess.run(
                ["docker", "exec", inv.system_name, *inv.argv]
            ).returncode
        except OSError as exc:
            print(f"{RED}❌ Error: Could not execute configured function '{inv.target_name}': {exc}{RESET}")
            return 1

    # "open" operation
    opener = shutil.which("xdg-open")
    if not opener:
        print(f"{RED}❌ Error: xdg-open is not available on this host.{RESET}")
        return 1

    target_val = inv.url
    if target_val and target_val.startswith("file://"):
        target_val = target_val[7:]

    try:
        subprocess.Popen(
            [opener, *inv.argv, target_val],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        print(f"{RED}❌ Error: Could not open configured target '{inv.target_name}': {exc}{RESET}")
        return 1
    return 0


def do_enter(sandbox: Sandbox, agent_name: str) -> None:
    settings, _ = sandbox.config.load_settings()
    if agent_name == "*":
        print(f"{RED}❌ Error: You cannot enter an interactive shell on multiple containers concurrently using '*' wildcards.{RESET}")
        sys.exit(1)

    agent = sandbox.config.get_container_config(settings, agent_name)
    if not agent:
        print(f"{RED}❌ Error: Agent '{agent_name}' is not defined in containers_settings.json.{RESET}")
        sys.exit(1)

    container_name = sandbox.config.resolve_container_name(agent_name)
    if not sandbox.is_container_running(container_name):
        print(f"{YELLOW}⚠️  Container '{container_name}' is not running. Automatically starting...{RESET}")
        res = sandbox.start_container(agent)
        if not res.success:
            print(f"{RED}❌ Error: Failed to start container: {res.message}{RESET}")
            sys.exit(1)

    print(f"{GREEN}📂 Slipping down into container sandbox '{container_name}' as unprivileged agent...{RESET}\n")
    subprocess.run(["docker", "exec", "-it", container_name, "bash"])


def do_logs(sandbox: Sandbox, agent: dict, requested_services: Optional[list[str]] = None) -> None:
    name = agent.get("name")
    container_name = sandbox.config.resolve_container_name(name)
    compose_path = agent.get("compose_path")

    if compose_path:
        compose_path = expand_path(compose_path)
        if not os.path.exists(compose_path):
            print(f"{RED}❌ Error: Compose file '{compose_path}' not found.{RESET}")
            return
        try:
            compose_env_files = sandbox.config.get_compose_env_files(agent)
            compose_environment = sandbox.config.get_compose_environment(agent)
        except ConfigError as exc:
            print(f"{RED}❌ Error: {exc}{RESET}")
            return

        requested_services = requested_services or agent.get("default_log_services", [])
        if not isinstance(requested_services, list) or any(
            not isinstance(service, str) or not service for service in requested_services
        ):
            print(f"{RED}❌ Error: requested Compose log services must be non-empty names.{RESET}")
            return

        allowed_services = agent.get("log_services", [])
        if not isinstance(allowed_services, list) or any(
            service not in allowed_services for service in requested_services
        ):
            print(f"{RED}❌ Error: one or more requested log services are not declared for '{name}'.{RESET}")
            return

        compose_bin = sandbox.config.get_compose_bin()
        compose_cmd = [compose_bin]
        for compose_env_file in compose_env_files:
            compose_cmd += ["--env-file", compose_env_file]

        print(
            f"{GREEN}📋 Streaming Compose logs for '{name}' services "
            f"{', '.join(requested_services)} (Ctrl+C to exit)...{RESET}"
        )
        try:
            subprocess.run(
                [*compose_cmd, "-f", compose_path, "logs", "-f", "--tail", "40", *requested_services],
                env=compose_environment,
            )
        except KeyboardInterrupt:
            print(f"\n{YELLOW}🛑 Stopped streaming logs.{RESET}")
        return

    print(f"{GREEN}📋 Streaming logs for container '{container_name}' (Ctrl+C to exit)...{RESET}")
    try:
        subprocess.run(["docker", "logs", "-f", container_name])
    except KeyboardInterrupt:
        print(f"\n{YELLOW}🛑 Stopped streaming logs.{RESET}")


def do_edit(sandbox: Sandbox) -> None:
    target = sandbox.config.settings_file if os.path.exists(sandbox.config.settings_file) else sandbox.config.settings_example_file
    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, target])


def do_build(sandbox: Sandbox) -> None:
    print(f"{GREEN}⚡ Building core agent image '{sandbox.config.image_name}'...{RESET}")
    try:
        res = sandbox.build_base_image()
        if not res.success:
            print(f"{RED}❌ Error: {res.message}{RESET}")
            sys.exit(1)
        print(f"{GREEN}🎉 Image built successfully!{RESET}")
    except ConfigError as exc:
        print(f"{RED}❌ Error: {exc}{RESET}")
        sys.exit(1)


def main(argv: Optional[list[str]] = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    sandbox = Sandbox()

    if not argv:
        pass
    else:
        cmd = argv[0].lower()

        if cmd in ["status", "ps", "dashboard"]:
            sys.exit(0 if do_status(sandbox) else 1)
        elif cmd == "edit":
            do_edit(sandbox)
            sys.exit(0)
        elif cmd == "in":
            sys.exit(do_in(sandbox, argv[1:]))
        elif cmd in ["help", "-h", "--help"]:
            pass
        else:
            try:
                settings, _ = sandbox.config.load_settings()
            except ConfigError as exc:
                print(f"{RED}❌ Error: {exc}{RESET}")
                sys.exit(1)

            request_args = argv[1:]
            log_services = []

            try:
                if cmd == "logs" and request_args:
                    target_containers, is_bulk = sandbox.config.resolve_targets(request_args[:1], settings)
                    log_services = request_args[1:]
                else:
                    target_containers, is_bulk = sandbox.config.resolve_targets(request_args, settings)
            except TargetNotFoundError as exc:
                print(f"{RED}❌ Error: {exc}{RESET}")
                sys.exit(1)

            if cmd in ["start", "up", "rebuild"]:
                errors = validate_all_settings(settings, config=sandbox.config)
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
                    selected_agents = [
                        sandbox.config.get_container_config(settings, target_name)
                        for target_name in target_containers
                    ]
                    if any(
                        agent is not None and not agent.get("compose_path")
                        for agent in selected_agents
                    ):
                        do_build(sandbox)

                if cmd == "explain":
                    do_explain(sandbox, target_containers)
                    sys.exit(0)

                for target_name in target_containers:
                    agent = sandbox.config.get_container_config(settings, target_name)
                    if not agent:
                        print(f"{RED}❌ Error: Container '{target_name}' is not defined in containers_settings.json.{RESET}")
                        continue

                    if cmd in ["start", "up"]:
                        res = sandbox.start_container(agent)
                        if res.success:
                            if not res.skipped:
                                print(f"🎉 {GREEN}{res.message}{RESET}")
                            else:
                                print(f"{YELLOW}⚠️  {res.message}{RESET}")
                        else:
                            print(f"{RED}❌ {res.message}{RESET}")
                    elif cmd in ["stop", "down"]:
                        res = sandbox.stop_container(agent)
                        if res.success:
                            if not res.skipped:
                                print(f"🧹 {GREEN}{res.message}{RESET}")
                            else:
                                print(f"{YELLOW}⚠️  {res.message}{RESET}")
                        else:
                            print(f"{RED}❌ {res.message}{RESET}")
                    elif cmd == "rebuild":
                        sandbox.stop_container(agent)
                        res = sandbox.start_container(agent)
                        if res.success:
                            print(f"🎉 {GREEN}{res.message}{RESET}")
                        else:
                            print(f"{RED}❌ {res.message}{RESET}")
                    elif cmd == "logs":
                        do_logs(sandbox, agent, log_services)
                sys.exit(0)

            elif cmd in ["enter", "shell"]:
                if len(target_containers) > 1 or is_bulk:
                    print(f"{RED}❌ Error: You cannot enter an interactive shell on multiple containers concurrently.{RESET}")
                    sys.exit(1)
                do_enter(sandbox, target_containers[0])
                sys.exit(0)
            else:
                print(f"{RED}❌ Unknown command: '{cmd}'{RESET}")

    print_header("SANDBOX MANAGEMENT COMMANDS")
    print(f"Usage: {BOLD}sandbox <command> [target_expression]{RESET}\n")
    print(f"       {BOLD}sandbox in c <container> [<open|run> <selector> [args...]]{RESET}\n")
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
    print(f"  {BOLD}logs <target> [service]{RESET}  Stream declared container or Compose service logs")
    print(f"  {BOLD}explain [target]{RESET}     Visualize the resolved lifecycle plan for container(s)")
    print(f"  {BOLD}in c ...{RESET}             List or call a container's configured commands")
    print(f"  {BOLD}edit{RESET}                 Open the containers_settings.json configuration file")
    print(f"  {BOLD}help{RESET}                 Print this help reference sheet\n")


if __name__ == "__main__":
    main()
