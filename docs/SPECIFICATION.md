# 🛡️ Docker Sandbox Protocol Specification

## 1. Executive Summary

The **Docker Sandbox Protocol** provides a hardened, reproducible multi-container orchestration architecture designed for automated workflows, autonomous AI agents, and developer sandboxes on Linux systems.

It achieves **gated autonomy** by enforcing:
- **Host Isolation:** Sandboxed environments cannot modify host user profiles, SSH keys, or administrative configurations.
- **Granular Network Control:** Loopback-only port bindings, inter-container communication whitelisting, and an egress HTTP/CONNECT proxy with domain glob filtering.
- **Resource Constraints:** Hard CPU core allocations and memory thresholds per container.
- **Lifecycle Pipeline:** Deterministic pre-boot host preparation, image builds with semver dependency presets, startup initialization, continuous healthchecks, and graceful shutdowns.
- **Sudo & Privilege Neutralization:** Sandboxes can have sudo completely removed at runtime without rebuilding images by mount-masking `/dev/null` over `/usr/bin/sudo`.
- **Docker Compose Delegation:** Seamless coexistence with production Docker Compose stacks alongside interactive sandboxes.

---

## 2. Directory Architecture & Layering

A standard deployment organizes files into dedicated functional tiers:

| Tier / Directory | Purpose | Access Control |
| :--- | :--- | :--- |
| `~/sandbox/workspace` | Active code workspaces & project checkouts | Agent Read/Write/Execute (`rwx`) |
| `~/sandbox/scratch` | Volatile scratchpad for temp files and builds | Agent Read/Write/Execute (`rwx`) |
| `~/sandbox/compose` | Compose YAML stacks for external services | Host Owned (`755`) |
| `~/.ssh`, `~/.gnupg` | Host user credentials & private keys | Completely restricted from agent (`---`) |

---

## 3. The Unprivileged Agent Sandbox User

The container runtime executes under an unprivileged user named `agent` (UID `1001`, GID `1001` by default).

* **UID Alignment:** Running UID `1001` allows clean POSIX ACL permissions mapping between the host and containers without file ownership collisions.
* **Shell Backdoor Prevention:** Because the host user's home directory is read-only or inaccessible to the container UID, agents cannot inject malicious scripts into `.bashrc`, `.profile`, or `.ssh/authorized_keys`.
* **Zero Privilege Escalation:** When `security.allow_sudo` is `false`, the orchestrator binds `/dev/null` over `/usr/bin/sudo`, making privilege escalation mechanically impossible inside the container.

---

## 4. Network Isolation & Egress Filtering

Containers can be configured into five discrete networking postures:

1. **`OFF` (`--network none`):** Completely airgapped container with no host, external, or container connectivity.
2. **`ON` (Full Access):** Unrestricted outbound internet access and container bridge resolution.
3. **`LOCAL` (Host Loopback):** Container can bind exposed ports to `127.0.0.1` on the host, but cannot reach the external internet.
4. **`CONTAINER` (Mesh Only):** Container can communicate only with designated sister containers within its group or network.
5. **`PROXY` (Domain Whitelist):** Container egress is routed through the Python socket proxy on port `8888`. Connections to unapproved external domains or IP addresses receive `HTTP 403 Forbidden` and are immediately terminated.

### Proxy Architecture (`config/proxy.py`)
- Standard HTTP requests and HTTPS `CONNECT` tunnels are intercepted.
- Wildcard glob domains (e.g. `*.github.com`, `pypi.org`) are validated against `/tmp/sandbox_proxy_rules.json`.
- Dropping `NET_ADMIN` default routing ensures sandboxed processes cannot bypass proxy environment variables.

---

## 5. Lifecycle Action Pipeline

Each container definition supports five execution phases:

1. **`host_prepare`:** Executes on the host before container boot. Ideal for directory provisioning (`ensure_dir`), filesystem mount checks (`require_mount`), and file initialization (`require_file`).
2. **`image_prepare`:** Executes on the Docker builder during container build time. Resolves dynamic presets (`install_preset`).
3. **`container_startup`:** Runs inside the container upon launch. Supports three execution policies:
   - `ALWAYS`: Executes every time the container boots.
   - `ONCE`: Executes only once during the lifetime of the container.
   - `NEVER`: Stored inside the container at `/usr/local/bin/startup.sh` for manual user invocation via `sandbox start`.
4. **`healthcheck`:** Runs verification checks on the host post-boot (e.g., verifying an HTTP endpoint via `http_check`).
5. **`shutdown`:** Executes teardown hooks before container destruction.

---

## 6. Dynamic Presets Engine (`presets/presets.json`)

The presets resolver allows declarative package dependencies in `containers_settings.json` using standard semver operators:
- `llama-server ~1.0`
- `nodejs >= 18`
- `python-pkgs`

The orchestrator reads `presets/presets.json`, builds layered Docker images dynamically on top of the base image, and caches images per container name.

---

## 7. Multi-Container Groupings & CLI Orchestration

Containers are grouped into logical identity classes (`container_groupings.json`):
- Dynamic naming rules (e.g. prefix `agent-`, suffix `.v1`).
- Bulk targeting (`sandbox start *`, `sandbox stop g {group1,group2}`).
- Single entrypoint interactive shells (`sandbox enter <name>`).
