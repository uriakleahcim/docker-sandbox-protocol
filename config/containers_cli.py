#!/usr/bin/env python3
"""Docker Sandbox Protocol CLI Orchestrator.

Backward-compatibility adapter delegating to the docker_sandbox SDK package.
"""
import json
import os
import shutil
import subprocess
import sys
from typing import Any, Optional

# Add src/ to sys.path
REAL_FILE = os.path.realpath(__file__)
REAL_DIR = os.path.dirname(REAL_FILE)
ROOT_DIR = os.environ.get("SANDBOX_ROOT", os.path.dirname(REAL_DIR) if os.path.basename(REAL_DIR) == "config" else REAL_DIR)
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from docker_sandbox import (
    ConfigError,
    ConfiguredCommandError,
    Sandbox,
    SandboxConfig,
    SandboxError,
    TargetNotFoundError,
    expand_path,
)
import docker_sandbox.cli as _cli
from docker_sandbox.cli import (
    BOLD,
    BLUE,
    CYAN,
    GREEN,
    RED,
    RESET,
    YELLOW,
    print_header,
)
import lifecycle_action_validator

# Path constants for backward compatibility
CONFIG_DIR = os.environ.get("SANDBOX_CONFIG_DIR", os.path.join(ROOT_DIR, "config"))
SETTINGS_FILE = os.environ.get("SANDBOX_SETTINGS_FILE", os.path.join(CONFIG_DIR, "containers_settings.json"))
SETTINGS_EXAMPLE_FILE = os.path.join(CONFIG_DIR, "containers_settings.example.json")
GROUPINGS_FILE = os.environ.get("SANDBOX_GROUPINGS_FILE", os.path.join(CONFIG_DIR, "container_groupings.json"))
GROUPINGS_EXAMPLE_FILE = os.path.join(CONFIG_DIR, "container_groupings.example.json")
PRESETS_FILE = os.environ.get("SANDBOX_PRESETS_FILE", os.path.join(ROOT_DIR, "presets", "presets.json"))
DOCKERFILE = os.path.join(CONFIG_DIR, "Dockerfile")
IMAGE_NAME = os.environ.get("SANDBOX_IMAGE_NAME", "agent-sandbox")
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
RULES_FILE = os.environ.get("SANDBOX_PROXY_RULES", os.path.join(RUNTIME_DIR, "sandbox_proxy_rules.json"))

SANDBOX_DOCKER_CONTEXT = os.environ.get("SANDBOX_DOCKER_CONTEXT")
if SANDBOX_DOCKER_CONTEXT:
    os.environ["DOCKER_CONTEXT"] = SANDBOX_DOCKER_CONTEXT


def _get_sandbox() -> Sandbox:
    cfg = SandboxConfig(
        root_dir=ROOT_DIR,
        config_dir=CONFIG_DIR,
        settings_file=SETTINGS_FILE,
        groupings_file=GROUPINGS_FILE,
        presets_file=PRESETS_FILE,
        dockerfile=DOCKERFILE,
        image_name=IMAGE_NAME,
        runtime_dir=RUNTIME_DIR,
        proxy_rules_file=RULES_FILE,
        docker_context=SANDBOX_DOCKER_CONTEXT,
    )
    return Sandbox(cfg)


def get_groupings_path() -> Optional[str]:
    return _get_sandbox().config.get_groupings_path()


def load_settings() -> dict[str, Any]:
    try:
        settings, _ = _get_sandbox().config.load_settings()
        return settings
    except ConfigError as e:
        print(f"{RED}❌ Error: {e}{RESET}")
        sys.exit(1)


def get_compose_bin() -> str:
    return _get_sandbox().config.get_compose_bin()


def get_compose_env_files(agent: dict[str, Any]):
    try:
        return _get_sandbox().config.get_compose_env_files(agent)
    except ConfigError as exc:
        print(f"{RED}❌ Error: {exc}{RESET}")
        return False


def get_compose_environment(agent: dict[str, Any]):
    try:
        return _get_sandbox().config.get_compose_environment(agent)
    except ConfigError as exc:
        print(f"{RED}❌ Error: {exc}{RESET}")
        return False


def execute_lifecycle_step(phase: str, step: dict[str, Any], container_name: Optional[str] = None):
    try:
        _, stdout = _get_sandbox().execute_lifecycle_step(phase, step, container_name)
        if stdout:
            print(f"    {stdout}")
    except Exception as exc:
        action_name = step.get("@action")
        print(f"{RED}❌ Error executing lifecycle action '{action_name}' in phase '{phase}':{RESET}")
        if hasattr(exc, "output"):
            print(getattr(exc, "output"))
        sys.exit(1)


def run_healthchecks(agent: dict[str, Any], container_name: str):
    lifecycle = lifecycle_action_validator.normalize_lifecycle(agent)
    healthcheck = lifecycle.get("healthcheck", [])
    if healthcheck:
        print(f"{GREEN}🔍 Running healthchecks for '{agent.get('name')}'...{RESET}")
        for i, step in enumerate(healthcheck):
            action_name = step.get("@action")
            print(f"  Verifying step [{i}]: {action_name}")
            execute_lifecycle_step("healthcheck", step, container_name)


def parse_version(v_str: str) -> list:
    return Sandbox.parse_version(v_str)


def compare_versions(v1: str, v2: str) -> int:
    return Sandbox.compare_versions(v1, v2)


def match_version(version: str, specifier: str) -> bool:
    return Sandbox.match_version(version, specifier)


def resolve_requirements(requirements: list[str]):
    return _get_sandbox().resolve_requirements(requirements)


def build_custom_image(agent_name: str, requirements: list[str]) -> str:
    return _get_sandbox().build_custom_image(agent_name, requirements)


def get_container_config(settings: dict[str, Any], name: str) -> Optional[dict[str, Any]]:
    return _get_sandbox().config.get_container_config(settings, name)


def get_default_container() -> str:
    return _get_sandbox().config.get_default_container()


def resolve_container_name(name: str) -> str:
    return _get_sandbox().config.resolve_container_name(name)


def is_container_running(container_name: str) -> bool:
    return _get_sandbox().is_container_running(container_name)


def is_container_exists(container_name: str) -> bool:
    return _get_sandbox().is_container_exists(container_name)


def get_docker_unavailable_reason() -> Optional[str]:
    return _get_sandbox().get_docker_unavailable_reason()


def append_runtime_security_options(cmd: list[str], security_config: dict[str, Any]) -> list[str]:
    return Sandbox.append_runtime_security_options(cmd, security_config)


def resolve_configured_invocation(agent: dict[str, Any], operation: str, selector: str, user_args: list[str]):
    return Sandbox.resolve_configured_invocation(agent, operation, selector, user_args)


def print_configured_command_catalog(agent: dict[str, Any]):
    _cli.print_configured_command_catalog(agent)


def do_in(args: list[str]) -> int:
    # Use monkeypatched globals if test modified them
    sb = Sandbox(
        SandboxConfig(
            root_dir=ROOT_DIR,
            config_dir=CONFIG_DIR,
            settings_file=SETTINGS_FILE,
            groupings_file=GROUPINGS_FILE,
            presets_file=PRESETS_FILE,
            dockerfile=DOCKERFILE,
            image_name=IMAGE_NAME,
            runtime_dir=RUNTIME_DIR,
            proxy_rules_file=RULES_FILE,
            docker_context=SANDBOX_DOCKER_CONTEXT,
        )
    )
    # Forward mocked methods if they were patched on this module
    if "load_settings" in globals():
        sb.config.load_settings = lambda: (load_settings(), False)
    if "is_container_running" in globals():
        sb.is_container_running = is_container_running
    if "get_docker_unavailable_reason" in globals():
        sb.get_docker_unavailable_reason = get_docker_unavailable_reason
    if "resolve_container_name" in globals():
        sb.config.resolve_container_name = resolve_container_name

    return _cli.do_in(sb, args)


def get_container_ip(container_name: str) -> Optional[str]:
    return _get_sandbox().get_container_ip(container_name)


def register_proxy_rules(container_name: str, allowed_domains: list[str], allowed_containers: list[str] = None):
    _get_sandbox().register_proxy_rules(container_name, allowed_domains, allowed_containers)


def unregister_proxy_rules(container_name: str):
    _get_sandbox().unregister_proxy_rules(container_name)


def register_container_ip(container_name: str):
    _get_sandbox().register_container_ip(container_name)


def ensure_proxy_running():
    _get_sandbox().ensure_proxy_running()


def do_build():
    _cli.do_build(_get_sandbox())


def setup_and_run_startup(agent: dict[str, Any], container_name: str):
    _get_sandbox().setup_and_run_startup(agent, container_name)


def parse_network_settings(agent: dict[str, Any]):
    return _get_sandbox().parse_network_settings(agent)


def start_agent(agent: dict[str, Any]):
    res = _get_sandbox().start_container(agent)
    if res.success:
        if not res.skipped:
            print(f"🎉 {GREEN}{res.message}{RESET}")
        else:
            print(f"{YELLOW}⚠️  {res.message}{RESET}")
    else:
        print(f"{RED}❌ {res.message}{RESET}")


def stop_agent(agent: dict[str, Any]):
    res = _get_sandbox().stop_container(agent)
    if res.success:
        if not res.skipped:
            print(f"🧹 {GREEN}{res.message}{RESET}")
        else:
            print(f"{YELLOW}⚠️  {res.message}{RESET}")
    else:
        print(f"{RED}❌ {res.message}{RESET}")


def do_enter(agent_name: str):
    _cli.do_enter(_get_sandbox(), agent_name)


def do_status() -> bool:
    return _cli.do_status(_get_sandbox())


def do_edit():
    _cli.do_edit(_get_sandbox())


def do_logs(agent: dict[str, Any], requested_services: Optional[list[str]] = None):
    _cli.do_logs(_get_sandbox(), agent, requested_services)


def do_explain(settings: dict[str, Any], target_containers: list[str]):
    _cli.do_explain(_get_sandbox(), target_containers)


def resolve_targets(args: list[str], settings: dict[str, Any]):
    try:
        return _get_sandbox().config.resolve_targets(args, settings)
    except TargetNotFoundError as exc:
        print(f"{RED}❌ Error: {exc}{RESET}")
        sys.exit(1)


def main():
    _cli.main()


if __name__ == "__main__":
    main()
