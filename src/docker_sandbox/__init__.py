"""Docker Sandbox Protocol SDK.

A robust Python framework and orchestration engine for autonomous AI agents and developer sandboxes.
"""

from docker_sandbox.client import Sandbox
from docker_sandbox.config import SandboxConfig, expand_path
from docker_sandbox.exceptions import (
    ConfigError,
    ConfiguredCommandError,
    DockerUnavailableError,
    LifecycleError,
    LifecycleExecutionError,
    LifecycleValidationError,
    SandboxError,
    TargetNotFoundError,
)
from docker_sandbox.lifecycle import (
    normalize_lifecycle,
    validate_action_step,
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

__version__ = "0.2.0"

__all__ = [
    "Sandbox",
    "SandboxConfig",
    "expand_path",
    # Exceptions
    "SandboxError",
    "ConfigError",
    "TargetNotFoundError",
    "DockerUnavailableError",
    "LifecycleError",
    "LifecycleValidationError",
    "LifecycleExecutionError",
    "ConfiguredCommandError",
    # Models
    "ContainerStatus",
    "StatusReport",
    "ActionResult",
    "CommandInvocation",
    "LifecycleValidationResult",
    # Lifecycle
    "normalize_lifecycle",
    "validate_action_step",
    "validate_agent_lifecycle",
    "validate_all_settings",
]
