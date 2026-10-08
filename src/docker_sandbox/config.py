"""Configuration and path management for Docker Sandbox Protocol SDK."""
import json
import os
import shutil
from typing import Any, Optional

from docker_sandbox.exceptions import ConfigError, TargetNotFoundError


def expand_path(p: str) -> str:
    """Expands ~, environment variables, and returns absolute path."""
    if not p:
        return p
    return os.path.abspath(os.path.expanduser(os.path.expandvars(p)))


class SandboxConfig:
    """Explicit paths and loaders for one Docker Sandbox Protocol instance.

    Package installation never owns an orchestration instance.  A consumer must
    select one through ``root_dir``/``config_dir`` or the corresponding
    ``SANDBOX_*`` environment variables.  Source-checkout use remains
    convenient: when the package is imported from this repository its root is
    discovered only if the adjacent ``config`` and ``scripts`` directories
    exist.
    """

    def __init__(
        self,
        root_dir: Optional[str] = None,
        config_dir: Optional[str] = None,
        settings_file: Optional[str] = None,
        groupings_file: Optional[str] = None,
        presets_file: Optional[str] = None,
        registry_file: Optional[str] = None,
        scripts_dir: Optional[str] = None,
        dockerfile: Optional[str] = None,
        image_name: Optional[str] = None,
        runtime_dir: Optional[str] = None,
        proxy_rules_file: Optional[str] = None,
        docker_context: Optional[str] = None,
    ):
        selected_config_dir = config_dir or os.environ.get("SANDBOX_CONFIG_DIR")
        selected_root_dir = root_dir or os.environ.get("SANDBOX_ROOT")
        if selected_root_dir:
            self.root_dir = os.path.abspath(selected_root_dir)
        elif selected_config_dir:
            # A configuration directory is conventionally <root>/config.
            self.root_dir = os.path.dirname(os.path.abspath(selected_config_dir))
        else:
            source_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
            )
            if not (
                os.path.isdir(os.path.join(source_root, "config"))
                and os.path.isdir(os.path.join(source_root, "scripts"))
            ):
                raise ConfigError(
                    "No Sandbox configuration was selected. Pass SandboxConfig("
                    "config_dir=...), set SANDBOX_CONFIG_DIR, or set SANDBOX_ROOT."
                )
            self.root_dir = source_root

        self.config_dir = os.path.abspath(
            selected_config_dir or os.path.join(self.root_dir, "config")
        )
        self.settings_file = os.path.abspath(
            settings_file or os.environ.get("SANDBOX_SETTINGS_FILE") or os.path.join(self.config_dir, "containers_settings.json")
        )
        self.settings_example_file = os.path.join(self.config_dir, "containers_settings.example.json")

        self.groupings_file = os.path.abspath(
            groupings_file or os.environ.get("SANDBOX_GROUPINGS_FILE") or os.path.join(self.config_dir, "container_groupings.json")
        )
        self.groupings_example_file = os.path.join(self.config_dir, "container_groupings.example.json")

        self.presets_file = os.path.abspath(
            presets_file or os.environ.get("SANDBOX_PRESETS_FILE") or os.path.join(self.root_dir, "presets", "presets.json")
        )
        self.registry_file = os.path.abspath(
            registry_file or os.environ.get("SANDBOX_REGISTRY_PATH") or os.path.join(self.config_dir, "lifecycle_action_registry.json")
        )
        self.scripts_dir = os.path.abspath(
            scripts_dir or os.environ.get("SANDBOX_SCRIPTS_DIR") or os.path.join(self.root_dir, "scripts")
        )
        self.dockerfile = os.path.abspath(
            dockerfile or os.path.join(self.config_dir, "Dockerfile")
        )
        self.image_name = image_name or os.environ.get("SANDBOX_IMAGE_NAME", "agent-sandbox")
        self.runtime_dir = runtime_dir or os.environ.get("XDG_RUNTIME_DIR", "/tmp")
        self.proxy_rules_file = os.path.abspath(
            proxy_rules_file or os.environ.get("SANDBOX_PROXY_RULES") or os.path.join(self.runtime_dir, "sandbox_proxy_rules.json")
        )

        # Keep process-global environment untouched. Callers that run Docker
        # commands can request this environment explicitly with
        # ``docker_environment``.
        self.docker_context = docker_context or os.environ.get("SANDBOX_DOCKER_CONTEXT")

    def docker_environment(self) -> dict[str, str]:
        """Return a child-process environment for this configured Docker context."""
        environment = os.environ.copy()
        if self.docker_context:
            environment["DOCKER_CONTEXT"] = self.docker_context
        return environment

    def get_groupings_path(self) -> Optional[str]:
        if os.path.exists(self.groupings_file):
            return self.groupings_file
        if os.path.exists(self.groupings_example_file):
            return self.groupings_example_file
        return None

    def load_settings(self, fallback_to_example: bool = True) -> tuple[dict[str, Any], bool]:
        """
        Loads configuration settings.
        Returns (settings_dict, is_example).
        Raises ConfigError if not found.
        """
        if not os.path.exists(self.settings_file):
            if fallback_to_example and os.path.exists(self.settings_example_file):
                with open(self.settings_example_file, "r") as f:
                    return json.load(f), True
            raise ConfigError(f"Configuration file not found at '{self.settings_file}'")

        try:
            with open(self.settings_file, "r") as f:
                return json.load(f), False
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in '{self.settings_file}': {e}") from e

    def load_groupings(self) -> dict[str, Any]:
        """Loads container groupings if available."""
        path = self.get_groupings_path()
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return data.get("container_groupings", {})
        except Exception:
            return {}

    def load_registry(self) -> dict[str, Any]:
        """Loads lifecycle action registry."""
        if not os.path.exists(self.registry_file):
            raise ConfigError(f"Action registry not found at '{self.registry_file}'")
        try:
            with open(self.registry_file, "r") as f:
                return json.load(f)
        except Exception as e:
            raise ConfigError(f"Failed to load action registry: {e}") from e

    def load_presets(self) -> dict[str, Any]:
        """Loads presets specification."""
        if not os.path.exists(self.presets_file):
            return {}
        try:
            with open(self.presets_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def get_container_config(self, settings: dict[str, Any], name: str) -> Optional[dict[str, Any]]:
        containers = settings.get("containers") or settings.get("agents", [])
        for container in containers:
            if container.get("name") == name:
                return container
        return None

    def get_default_container(self) -> str:
        groupings = self.load_groupings()
        for grp, info in groupings.items():
            default_c = info.get("default_container")
            if default_c:
                return default_c
        return "dev-sandbox"

    def resolve_container_name(self, name: str) -> str:
        groupings = self.load_groupings()
        for grp, info in groupings.items():
            if name in info.get("containers", []):
                naming = info.get("naming", {})
                prefix = naming.get("prefix", "")
                suffix = naming.get("suffix", "")
                return f"{prefix}{name}{suffix}"
        return name

    def get_compose_bin(self) -> str:
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

    def get_compose_env_files(self, agent: dict[str, Any]) -> list[str]:
        """Return ordered Compose environment files without loading them into the process."""
        single_file = agent.get("compose_env_file")
        multiple_files = agent.get("compose_env_files")
        if single_file is not None and multiple_files is not None:
            raise ConfigError(f"'{agent.get('name')}' cannot set both compose_env_file and compose_env_files.")
        if multiple_files is not None:
            if not isinstance(multiple_files, list) or not multiple_files:
                raise ConfigError(f"compose_env_files for '{agent.get('name')}' must be a non-empty path list.")
            env_files = multiple_files
        elif single_file is not None:
            env_files = [single_file]
        else:
            return []

        resolved_files = []
        for env_file in env_files:
            if not isinstance(env_file, str) or not env_file:
                raise ConfigError(f"every Compose environment file for '{agent.get('name')}' must be a path string.")
            resolved = expand_path(env_file)
            if not os.path.isfile(resolved):
                raise ConfigError(f"Compose env file '{resolved}' not found.")
            resolved_files.append(resolved)
        return resolved_files

    def get_compose_environment(self, agent: dict[str, Any]) -> dict[str, str]:
        """Merge declared non-secret Compose variables into a dictionary."""
        declared = agent.get("environment", {})
        if not isinstance(declared, dict):
            raise ConfigError(f"environment for '{agent.get('name')}' must be an object.")
        env = self.docker_environment()
        env.update({str(k): str(v) for k, v in declared.items()})
        return env

    def resolve_targets(self, args: list[str] | str, settings: dict[str, Any]) -> tuple[list[str], bool]:
        """
        Resolves target expression to a list of container names.
        Returns (target_container_names, is_batch).
        """
        if isinstance(args, str):
            args = [args]
        if not args:
            return [self.get_default_container()], False

        first_arg = args[0].lower()
        if first_arg in ["g", "group"]:
            if len(args) < 2:
                raise TargetNotFoundError("Grouping name(s) not specified. Usage: g <group_name> or g {group1,group2}")

            group_expr = " ".join(args[1:]).strip()
            if group_expr.startswith("{") and group_expr.endswith("}"):
                group_expr = group_expr[1:-1]

            groups = [g.strip() for g in group_expr.split(",") if g.strip()]
            groupings = self.load_groupings()
            containers = settings.get("containers") or settings.get("agents", [])
            target_containers = []

            for g in groups:
                if g in groupings:
                    target_containers.extend(groupings[g].get("containers", []))
                elif any(c.get("name") == g for c in containers):
                    target_containers.append(g)

            if not target_containers:
                raise TargetNotFoundError("No valid containers resolved for specified groupings.")

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
