# Python SDK Modularization and Consumer Bindings

## Outcome

Docker Sandbox Protocol is consumable as a versioned Python package without
calling its CLI. Each consumer supplies the configuration directory it is
authorized to control or inspect; no consumer discovers an arbitrary
`sandbox` executable from `PATH`.

## Contract

- `docker_sandbox` is the supported programmatic public API.
- `SandboxConfig` owns explicit paths to the configuration, registry, scripts,
  presets, and runtime metadata required by an orchestration instance.
- The CLI is an optional adapter over the same public API.
- Bias Graph Feed uses the SDK only to validate and report the declared
  lifecycle configuration that owns its Compose service.
- Omacale uses a narrow, read-only helper and a validated Python environment;
  it never sends arbitrary commands, paths, or credentials into the SDK.

## Non-goals

- Embedding Docker Sandbox Protocol source into its consumers.
- Giving Omacale lifecycle mutation or Docker control.
- Relocating live service data or credentials.
