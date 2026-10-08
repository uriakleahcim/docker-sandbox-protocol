# Docker Sandbox Protocol Repository Guidance

## Scope and Identity

These instructions apply to this repository and all descendants.

The canonical checkout is:

```text
/home/uriak/Work/AppSource/com.github/docker-sandbox-protocol
```

The user may refer to this project as **Docker Sandbox Protocol**, **Sandbox Protocol**, **Docker harness**, **container harness**, or **Docker sandbox**. Unless another checkout is explicitly named, all of those terms resolve to this repository.

## Purpose

Docker Sandbox Protocol is the control plane for declarative container sandboxes and service containers. It manages container definitions, group resolution, lifecycle actions, resource and network policy, runtime status, and persistent session conventions.

Keep the source/control plane separate from runtime data:

- Source and active local configuration: this repository
- Runtime storage: `/home/uriak/sandbox`
- Runtime guidance: `/home/uriak/sandbox/AGENTS.md`

Read both this file and the runtime `AGENTS.md` before moving mounts, persistent data, session state, or service directories.

## Repository Map

```text
bin/sandbox
  -> launcher and environment setup
src/docker_sandbox/
  -> Core Python SDK framework (client, models, config, lifecycle, exceptions, cli)
config/containers_cli.py
  -> Backward-compatibility CLI orchestration adapter
config/containers_settings.json
  -> ignored active local container inventory
config/container_groupings.json
  -> ignored active local group inventory
config/*.example.json
  -> tracked reusable templates, not the host's live inventory
config/lifecycle_action_validator.py
  -> Backward-compatibility lifecycle schema validation adapter
config/lifecycle_action_registry.json
  -> allowed lifecycle actions and arguments
scripts/
  -> lifecycle action implementations
presets/presets.json
  -> image-build dependency presets
docs/
  -> protocol and lifecycle documentation
architect/
  -> reports and any explicitly created planning records
```

Execution path:

```text
sandbox command
  -> load active settings and groupings
  -> validate lifecycle actions
  -> resolve target/container name
  -> prepare image or delegate Compose
  -> create/start/stop Docker resources
  -> run startup and health actions
  -> report runtime state
```

## Active Configuration Versus Templates

- Treat `config/containers_settings.json` and `config/container_groupings.json` as this host's active local inventory. They are intentionally ignored by Git.
- Treat `config/*.example.json` as portable project templates.
- Never edit an example file merely to add, remove, or reconfigure a local container.
- When the user explicitly requests a template or installer-default change, update the example, documentation, and fresh-install behavior together.
- Keep active group references consistent with active container names. Do not leave stale group members or defaults after removing a container declaration.

## Runtime Storage Contract

Runtime data belongs under `/home/uriak/sandbox`, not in this checkout.

- `groups/<group>/<service>/`: persistent service configuration, data, indexes, objects, and caches
- `sessions/<session-id>/`: session workspace and scratch storage
- `state/`: harness-owned session metadata, logs, and locks

Do not place canonical source checkouts, global agent memory, or unrelated user files in the runtime tree. Preserve container-specific ownership; do not recursively change ownership across the runtime root.

The active `agent-services` group contains capabilities consumed by agents, such as SearXNG search, Meshingress MCP access, RAG/index services, memory, crawling, and embeddings. Create a service entry only when a concrete capability is installed.

## Current Local Service Context

The active container inventory currently contains SearXNG:

- Container: `searxng`
- Active group: `agent-services`
- Host endpoint: `http://127.0.0.1:18080`
- Persistent paths: `/home/uriak/sandbox/groups/agent-services/searxng/`
- Exposure must remain loopback-only unless the user explicitly authorizes broader access.

Meshingress is a separate, actively developed project. Its canonical source checkout remains:

```text
/home/uriak/Work/AppSource/com.github/meshingress
```

Do not copy Meshingress source into this repository or the runtime tree. Container integration may build or mount it deliberately, while persistent Meshingress runtime data belongs under the appropriate runtime service directory.

## Editing and Worktree Rules

- Inspect `git status` before editing and preserve unrelated user changes.
- The repository may contain intentional local launcher changes; do not revert them without explicit authorization.
- Use `apply_patch` for source and configuration edits.
- Do not commit, push, or create a remote unless requested.
- Keep local operational changes in active ignored JSON files; keep reusable project changes in tracked source/templates only when authorized.
- Do not add a core CLI verb for one target-specific operation. Stage such
  behavior in that target's declared `commands` node and invoke it through
  `sandbox in c <target> run <function>`. Change core CLI behavior only to fix
  an existing defect or for an explicitly approved cross-target harness feature.
- Validate JSON after every active inventory or grouping edit.
- If a change affects lifecycle actions, update the registry, validator, implementation, examples, and documentation coherently.
- Prefer configuring existing declarative lifecycle actions over adding parallel startup, health, or shutdown mechanisms. Do not duplicate work already owned by an image entrypoint or Docker restart policy.

## Container Operations

- Prefer the harness commands over direct `docker run`, `docker stop`, or `docker rm` so declared lifecycle and state remain coherent.
- Use `sandbox explain <target>` before starting or rebuilding a changed declaration.
- Inspect actual Docker mounts and port bindings after persistent-path or network changes.
- Docker access from restricted agent execution may require `pkexec`. Do not weaken Docker socket permissions as a workaround.
- Never expose a service publicly merely because its image defaults to a public bind.
- Resolve exact container and filesystem targets before destructive operations.
- Stop the owning container before moving persistent mounts, verify the new service, and remove the old path only after confirming it is empty.

## Required Validation

For configuration-only changes:

```bash
python3 -m json.tool config/containers_settings.json
python3 -m json.tool config/container_groupings.json
sandbox explain '<target>'
```

For Python changes:

```bash
python3 -m py_compile config/containers_cli.py config/lifecycle_action_validator.py src/docker_sandbox/*.py
python3 -m unittest discover -s tests
```

Also run, as applicable:

- `git diff --check`
- Runtime status with Docker access
- Docker inspection of mounts, limits, restart policy, and port scope
- Service-specific HTTP/API health checks
- Start/stop/rebuild smoke tests for each affected execution path

## Known Runtime Caveats

Do not mistake these current behaviors for guaranteed policy enforcement:

- `start`/`rebuild` currently builds the generic `agent-sandbox` image even for custom-image or Compose targets.
- Docker command failures can be displayed as `NOT CREATED` because some status checks do not distinguish daemon/access errors from absence.
- `http_check` currently makes one request without connection-refusal retries. An immediate post-create probe can falsely fail while a service is still opening its port; do not present it as a cold-start readiness guarantee unless retry behavior is added to the existing action and validated.
- Custom-image containers such as SearXNG rely on their image entrypoint. The harness does not run its generated `container_startup` script for the custom-image path, so do not configure a duplicate application start command there.
- Compose delegation does not apply every limit, mount, network, or security field displayed in the active declaration.
- `toggle_logging` and `network.host_access.allowed_hosts` are declared but currently have no runtime enforcement path.
- The sample AI service is a demonstration, not a validated inference service.

Consult `architect/reports/` for current inspection evidence before implementing cleanup or runtime refactors.

## Safety Boundaries

- Do not delete or rewrite tracked examples solely because they are unused on this host.
- Do not remove a persistent service directory because its container is stopped or absent.
- Do not use broad recursive deletion against `/home/uriak/sandbox`, this repository, or `/home/uriak/Work`.
- Recheck that candidate directories are empty and unmounted immediately before removal.
- Preserve canonical project boundaries and unrelated running containers, including services not owned by this harness.
