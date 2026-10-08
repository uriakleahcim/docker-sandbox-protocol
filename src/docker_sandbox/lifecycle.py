"""Lifecycle schema validation and normalization for Docker Sandbox Protocol SDK."""
import json
import os
import re
from typing import Any, Optional

from docker_sandbox.config import SandboxConfig


def normalize_lifecycle(agent_config: dict[str, Any]) -> dict[str, Any]:
    """
    Normalizes legacy startup and prep settings into the new lifecycle schema.
    Provides backward compatibility for older declaration formats.
    """
    normalized = {}

    # 1. Existing new lifecycle block
    if "lifecycle" in agent_config:
        normalized = json.loads(json.dumps(agent_config["lifecycle"]))

    # 2. Map legacy pre_start -> lifecycle.host_prepare
    pre_start = agent_config.get("pre_start", [])
    if pre_start and "host_prepare" not in normalized:
        steps = []
        for cmd in pre_start:
            if cmd.startswith("mkdir -p "):
                path = cmd.split("mkdir -p ")[1].strip().strip('"').strip("'")
                steps.append({"@action": "ensure_dir", "path": path})
            elif cmd.startswith("touch "):
                path = cmd.split("touch ")[1].strip().strip('"').strip("'")
                steps.append({"@action": "require_file", "path": path})
            else:
                steps.append({"@action": "shell", "command": cmd})
        normalized["host_prepare"] = steps

    # 3. Map legacy runtime.startup.sh -> lifecycle.container_startup.steps
    runtime = agent_config.get("runtime", {})
    if isinstance(runtime, dict):
        startup_behavior = runtime.get("startup_behavior", "NEVER")
        startup_sh = runtime.get("startup.sh") or runtime.get("startup_commands")

        if startup_sh and "container_startup" not in normalized:
            steps = []
            commands = [startup_sh] if isinstance(startup_sh, str) else startup_sh
            for cmd in commands:
                steps.append({"@action": "shell", "command": cmd})
            normalized["container_startup"] = {
                "behavior": startup_behavior,
                "steps": steps,
            }

    return normalized


def validate_action_step(
    phase: str,
    step: dict[str, Any],
    index: int,
    registry: dict[str, Any],
    scripts_dir: str,
    errors: list[str],
) -> None:
    # Safety Check: Reject @function
    if "@function" in step:
        errors.append(f'ERROR lifecycle.{phase}[{index}]: "@function" is not allowed. Use "@action".')
        return

    # Safety Check: Reject 'type'
    if "type" in step:
        errors.append(f'ERROR lifecycle.{phase}[{index}]: "type" is not allowed for lifecycle action dispatch. Use "@action".')
        return

    # 1. Verify @action is present
    if "@action" not in step:
        errors.append(f'ERROR lifecycle.{phase}[{index}]: missing @action.')
        return

    action_name = step["@action"]

    # 2. Confirm action exists in registry
    if action_name not in registry.get("actions", {}):
        errors.append(f'ERROR lifecycle.{phase}[{index}]: unknown action "{action_name}".')
        return

    action_meta = registry["actions"][action_name]

    # 3. Confirm phase is allowed
    if phase not in action_meta.get("allowed_phases", []):
        errors.append(f'ERROR lifecycle.{phase}[{index}]: action "{action_name}" is not allowed in phase "{phase}".')
        return

    # 4. Confirm corresponding script file exists
    script_name = action_meta.get("script", "")
    script_path = os.path.join(scripts_dir, script_name)
    if not os.path.exists(script_path):
        errors.append(f'ERROR lifecycle.{phase}[{index}]: script "{script_name}" not found at {script_path}.')
        return

    # 5. Verify required arguments are present
    for req_arg in action_meta.get("required", []):
        if req_arg not in step:
            errors.append(f'ERROR lifecycle.{phase}[{index}]: missing required argument "{req_arg}" for action "{action_name}".')

    # 6. Reject unknown arguments
    allowed_args = set(action_meta.get("required", []) + action_meta.get("optional", []) + ["@action"])
    for key in step.keys():
        if key not in allowed_args:
            errors.append(f'ERROR lifecycle.{phase}[{index}]: unknown argument "{key}" for action "{action_name}".')

    # 7. Validate argument types and schemas
    arg_schema = action_meta.get("arg_schema", {})
    for arg_name, arg_val in step.items():
        if arg_name == "@action":
            continue
        if arg_name not in arg_schema:
            continue

        rules = arg_schema[arg_name]
        expected_type = rules.get("type")

        # Type checking
        if expected_type == "string" and not isinstance(arg_val, str):
            errors.append(f'ERROR lifecycle.{phase}[{index}]: argument "{arg_name}" must be a string (got {type(arg_val).__name__}).')
        elif expected_type == "integer" and not isinstance(arg_val, int) and not (isinstance(arg_val, str) and arg_val.isdigit()):
            errors.append(f'ERROR lifecycle.{phase}[{index}]: argument "{arg_name}" must be an integer (got {type(arg_val).__name__}).')
        elif expected_type == "boolean" and not isinstance(arg_val, bool):
            errors.append(f'ERROR lifecycle.{phase}[{index}]: argument "{arg_name}" must be a boolean (got {type(arg_val).__name__}).')
        elif expected_type == "array" and not isinstance(arg_val, list):
            errors.append(f'ERROR lifecycle.{phase}[{index}]: argument "{arg_name}" must be an array/list (got {type(arg_val).__name__}).')

        # Range / Minimum checking for integers
        if expected_type == "integer" and "minimum" in rules:
            try:
                val_int = int(arg_val)
                if val_int < rules["minimum"]:
                    errors.append(f'ERROR lifecycle.{phase}[{index}]: argument "{arg_name}" must be >= {rules["minimum"]}.')
            except ValueError:
                pass

        # Pattern checking (Regex) for strings
        if expected_type == "string" and "pattern" in rules:
            if not re.match(rules["pattern"], str(arg_val)):
                errors.append(f'ERROR lifecycle.{phase}[{index}]: argument "{arg_name}" value "{arg_val}" does not match pattern {rules["pattern"]}.')

        # Absolute or expanded path validation
        if expected_type == "string" and rules.get("must_be_absolute", False):
            expanded_val = os.path.expanduser(str(arg_val))
            if not os.path.isabs(expanded_val):
                errors.append(f'ERROR lifecycle.{phase}[{index}]: argument "{arg_name}" path must be absolute (got "{arg_val}").')


def validate_agent_lifecycle(
    agent_config: dict[str, Any],
    registry: Optional[dict[str, Any]] = None,
    scripts_dir: Optional[str] = None,
    config: Optional[SandboxConfig] = None,
) -> list[str]:
    """
    Validates a single agent/container settings block.
    Returns a list of error strings (empty if valid).
    """
    errors: list[str] = []
    if config is None:
        config = SandboxConfig()

    if registry is None:
        try:
            registry = config.load_registry()
        except Exception as e:
            return [f"SYSTEM ERROR: Failed to load action registry: {str(e)}"]

    if scripts_dir is None:
        scripts_dir = config.scripts_dir

    lifecycle = normalize_lifecycle(agent_config)

    valid_phases = ["host_prepare", "image_prepare", "container_startup", "healthcheck", "shutdown"]
    for phase, content in lifecycle.items():
        if phase not in valid_phases:
            errors.append(f'ERROR: unknown lifecycle phase "{phase}".')
            continue

        if phase == "container_startup":
            if not isinstance(content, dict):
                errors.append('ERROR: lifecycle.container_startup must be an object/dict.')
                continue
            steps = content.get("steps", [])
            if not isinstance(steps, list):
                errors.append('ERROR: lifecycle.container_startup.steps must be a list.')
                steps = []
            for i, step in enumerate(steps):
                validate_action_step(phase, step, i, registry, scripts_dir, errors)
        else:
            if not isinstance(content, list):
                errors.append(f'ERROR: lifecycle.{phase} must be a list of action steps.')
                continue
            for i, step in enumerate(content):
                validate_action_step(phase, step, i, registry, scripts_dir, errors)

    return errors


def validate_all_settings(
    settings_data: dict[str, Any],
    registry: Optional[dict[str, Any]] = None,
    scripts_dir: Optional[str] = None,
    config: Optional[SandboxConfig] = None,
) -> dict[str, list[str]]:
    """
    Validates all containers in settings data.
    Returns dict of container_name -> list_of_errors.
    """
    all_errors = {}
    containers = settings_data.get("containers") or settings_data.get("agents", [])
    for agent in containers:
        agent_name = agent.get("name", "unknown")
        errors = validate_agent_lifecycle(agent, registry=registry, scripts_dir=scripts_dir, config=config)
        if errors:
            all_errors[agent_name] = errors
    return all_errors
