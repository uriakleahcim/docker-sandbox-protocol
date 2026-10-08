# Project Adapter

## Project Identity

- projectName: Docker Sandbox Protocol
- repository: `/home/uriak/Work/AppSource/com.github/docker-sandbox-protocol`
- projectType: Python SDK and optional terminal interface for declarative Docker service control
- primaryLanguages: Python, Bash, JSON
- buildTools: setuptools and Python unittest
- testCommands: `python3 -m unittest discover -s tests`
- packageManager: pip / setuptools

## Runtime / Framework Notes

- The importable contract is `docker_sandbox`; the `sandbox` terminal command is a human-facing adapter.
- Package code, active container configuration, and runtime service data are separate: callers supply a `SandboxConfig` location and the runtime belongs under `/home/uriak/sandbox`.
- Docker operations are effects. Status and plan validation are read-only; lifecycle methods start, stop, build, and remove Docker resources.

## Verification Commands

```bash
python3 -m py_compile src/docker_sandbox/*.py config/containers_cli.py config/lifecycle_action_validator.py
python3 -m unittest discover -s tests
git diff --check
```

## Architect Rules

- Use Architect for cross-consumer API changes, configuration-boundary changes, or lifecycle semantics—not ordinary maintenance.
- Preserve compatibility adapters until a documented replacement path exists.
- Do not record credentials, Docker socket paths, or active runtime configuration values in Architect documents.
