"""Custom exceptions for Docker Sandbox Protocol SDK."""

class SandboxError(Exception):
    """Base exception for all Docker Sandbox Protocol errors."""
    pass


class ConfigError(SandboxError):
    """Raised when configuration files are missing, malformed, or invalid."""
    pass


class TargetNotFoundError(SandboxError):
    """Raised when a requested container, group, or wildcard target does not match any declarations."""
    pass


class DockerUnavailableError(SandboxError):
    """Raised when the Docker daemon is unreachable or unauthorized."""
    pass


class LifecycleError(SandboxError):
    """Base exception for lifecycle action errors."""
    pass


class LifecycleValidationError(LifecycleError):
    """Raised when lifecycle actions fail schema validation."""
    def __init__(self, message: str, errors: list[str] = None):
        super().__init__(message)
        self.errors = errors or []


class LifecycleExecutionError(LifecycleError):
    """Raised when a lifecycle step command fails during execution."""
    def __init__(self, phase: str, step: dict, returncode: int, output: str = ""):
        action = step.get("@action", "unknown")
        super().__init__(f"Lifecycle step '{action}' in phase '{phase}' failed with exit code {returncode}")
        self.phase = phase
        self.step = step
        self.returncode = returncode
        self.output = output


class ConfiguredCommandError(SandboxError):
    """Raised when a target command selector or argument list is invalid."""
    pass
