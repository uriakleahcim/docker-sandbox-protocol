# Rootless Sandbox Hardening Design

## Implementation Status

Completed on 2026-09-30. The `sandbox-rootless` context is the normal user
default, the rootless user socket is enabled, SearXNG has been migrated and
verified, and the rootful daemon retains only the separately managed Coolify
stack. Host-root Docker access still requires an explicit privileged command
against the `default` context.

## Scope

This design applies only to Docker Sandbox Protocol and its SearXNG service.
The existing rootful Docker daemon and the separately managed Coolify stack
remain unchanged.

The original design phase made no system changes. The later authorized
implementation installed the required packages, enabled the user daemon,
created the context, remapped the SearXNG cache, and completed the cutover.

## Verified Current State

- `uriak` is not a permanent member of the `docker` group.
- The system Docker daemon is rootful.
- SearXNG is not privileged, has no added capabilities or devices, and does
  not mount the Docker socket.
- SearXNG publishes `127.0.0.1:18080` only.
- The SearXNG image defines user and group `977:977`, but the current live
  container starts its processes as container root.
- UID `977:977` can read the existing `settings.yml`, cannot write it, can
  write the cache, and can import the SearXNG application.
- The host has `newuidmap`, `newgidmap`, 65,536 subordinate UIDs/GIDs for
  `uriak`, enabled unprivileged user namespaces, and cgroup v2.
- `rootlesskit`, `slirp4netns`/`passt`, and the Arch rootless Docker user-unit
  package are not installed.
- Coolify Sentinel uses the rootful Docker socket read-write and host PID
  namespace. Coolify Proxy uses the Docker socket read-only.

## Source and Pending Configuration Changes

The harness supports these declarative controls for the next deliberate
SearXNG recreation:

```json
"security": {
  "allow_sudo": false,
  "run_as_user": "977:977",
  "cap_drop": ["ALL"],
  "no_new_privileges": true
}
```

The SearXNG configuration bind is read-only. Its cache remains writable.

`SANDBOX_DOCKER_CONTEXT` pins all Docker subprocesses and lifecycle scripts to
an existing Docker context without changing the user's global context.

## Target Architecture

1. Keep the system rootful Docker daemon for Coolify.
2. Add a separate rootless Docker daemon owned by `uriak`.
3. Create a context named `sandbox-rootless` pointing to
   `unix:///run/user/1000/docker.sock`.
4. Run the Sandbox Protocol only with
   `SANDBOX_DOCKER_CONTEXT=sandbox-rootless`.
5. Place only Sandbox Protocol containers in that daemon. This creates a
   daemon-level boundary from Coolify and its Docker-socket consumers.
6. Run SearXNG as UID/GID `977:977`, with all capabilities dropped,
   no-new-privileges enabled, config read-only, cache writable, and the host
   port bound to loopback.

## Cross-Container Boundary

Do not currently change `network.container_access` to an empty list as a
standalone fix. The existing restricted-network path:

- adds `NET_ADMIN`;
- assumes the rootful gateway `172.17.0.1`;
- registers only containers declared in the active Sandbox inventory; and
- can therefore treat undeclared Coolify IPs as ordinary external addresses
  when external access is `"*"`.

The first effective boundary is the separate rootless daemon, which cannot
discover or directly address the rootful Coolify container networks. Before a
second Sandbox service is added, implement one isolated user-defined network
per service or replace the proxy route manipulation with context-aware network
policy that discovers every peer in the selected daemon.

## Cache Ownership Migration

Rootless UID mapping means container UID 977 maps to a subordinate host UID,
not host UID 977. Do not recursively `chown` the runtime tree from the host.

During the later migration window, prepare only the exact SearXNG cache mount
from inside the rootless user namespace, then verify it is writable as
container UID 977. The configuration mount needs no ownership change because
it is read-only and already world-readable.

## Executed Migration Procedure

1. Install the Arch rootless prerequisites through Omarchy package management.
2. Enable the rootless Docker user service/socket without disabling system
   Docker.
3. Create and verify the `sandbox-rootless` context.
4. Pull the SearXNG image into the rootless daemon.
5. Prepare the exact cache ownership inside the rootless namespace.
6. Validate the fully resolved rootless `docker run` command without changing
   the running rootful service.
7. Schedule a short cutover: stop only rootful SearXNG, start rootless SearXNG,
   and verify `127.0.0.1:18080/config` and JSON search.
8. Inspect live user, capabilities, mounts, port bindings, context, and daemon
   security options.
9. If validation fails, stop the rootless instance and restart the untouched
   rootful SearXNG container.

## Acceptance Criteria

- Coolify remains on the rootful daemon and is not restarted or reconfigured.
- `sandbox status` uses `sandbox-rootless` without `pkexec` or Docker-group
  membership.
- SearXNG runs as `977:977` with `CapAdd=null`, all capabilities dropped,
  `no-new-privileges=true`, and `Privileged=false`.
- No Docker socket is mounted into SearXNG.
- Config is read-only; cache is writable only by the mapped SearXNG identity.
- Port 18080 is loopback-only.
- SearXNG cannot discover or reach rootful Coolify container addresses.
- Rootful SearXNG remains available as a rollback until the rootless service is
  fully verified.
