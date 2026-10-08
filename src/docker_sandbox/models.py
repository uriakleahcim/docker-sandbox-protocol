"""Data models and structured results for Docker Sandbox Protocol SDK."""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ContainerStatus:
    """Status details for a single declared container."""
    name: str
    system_name: str
    group: str
    raw_status: str  # "RUNNING", "STOPPED", "NOT CREATED"
    network_mode: str  # "OFF", "ON", "LOCAL", "CONTAINER", "PROXY"
    sudo_allowed: bool
    cpu_limit: str
    memory_limit: str
    is_running: bool
    exists: bool
    raw_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class StatusReport:
    """Comprehensive status overview across all container groups."""
    docker_available: bool
    docker_error: Optional[str]
    groups: dict[str, list[ContainerStatus]] = field(default_factory=dict)

    @property
    def total_containers(self) -> int:
        return sum(len(containers) for containers in self.groups.values())

    @property
    def running_containers(self) -> int:
        return sum(
            1 for containers in self.groups.values()
            for c in containers if c.is_running
        )


@dataclass
class ActionResult:
    """Result of an operation on a container (start, stop, etc.)."""
    target: str
    container_name: str
    action: str
    success: bool
    message: str
    skipped: bool = False
    details: Optional[dict[str, Any]] = None


@dataclass
class CommandInvocation:
    """Resolved command execution details."""
    container_name: str
    system_name: str
    command_type: str  # "run", "open", etc.
    target_name: str
    argv: list[str] = field(default_factory=list)
    url: Optional[str] = None
    env: dict[str, str] = field(default_factory=dict)
    requires_running: bool = True
    allow_args: bool = False
    is_interactive: bool = False


@dataclass
class LifecycleValidationResult:
    """Result of lifecycle action validation for a container."""
    container_name: str
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    phases: dict[str, Any] = field(default_factory=dict)
