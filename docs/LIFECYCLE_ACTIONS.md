# 🔄 Lifecycle Action Reference

The Docker Sandbox Protocol features a declarative lifecycle action registry (`config/lifecycle_action_registry.json`) validated strictly against schemas before any container operation executes.

---

## Supported Lifecycle Phases

| Phase | Execution Context | Description |
| :--- | :--- | :--- |
| `host_prepare` | Host OS | Runs before container boot. Used for host mounts, permissions, and directory preparation. |
| `image_prepare` | Image Builder | Runs during Docker build time to install software layers. |
| `container_startup` | Inside Container | Runs inside the container at startup. Governed by behavior policy (`ALWAYS`, `ONCE`, `NEVER`). |
| `healthcheck` | Host OS | Runs after container boot to verify service health and port availability. |
| `shutdown` | Host OS / Container | Runs prior to container stop and removal. |

---

## Action Reference

### 1. `ensure_dir`
Ensures that a specified directory exists on the host, creating parent directories and setting appropriate permissions if needed.
- **Allowed Phases:** `host_prepare`, `shutdown`
- **Runs On:** Host
- **Parameters:**
  - `path` (string, required): Directory path to ensure exists. Supports `~` expansion.
  - `owner` (string, optional): User/group ownership to apply.
  - `mode` (string, optional): Octal permissions mode (e.g. `"0755"`).

```json
{
  "@action": "ensure_dir",
  "path": "~/sandbox/workspace/my-app",
  "mode": "0755"
}
```

---

### 2. `require_mount`
Validates that a designated filesystem path is an active mountpoint. Optionally attempts to mount it via `sudo mount` and verifies write access.
- **Allowed Phases:** `host_prepare`, `healthcheck`
- **Runs On:** Host
- **Parameters:**
  - `path` (string, required): Filesystem path to verify.
  - `must_be_writable` (boolean, optional): If `true`, creates and removes a temporary test file to verify write access.

```json
{
  "@action": "require_mount",
  "path": "/mnt/external-data",
  "must_be_writable": true
}
```

---

### 3. `require_file`
Verifies that a file exists on the host, or creates an empty file if missing.
- **Allowed Phases:** `host_prepare`, `healthcheck`
- **Runs On:** Host
- **Parameters:**
  - `path` (string, required): File path to verify.
  - `create_if_missing` (boolean, optional): Create file if it does not exist (default `true`).

```json
{
  "@action": "require_file",
  "path": "~/sandbox/data/database.sqlite",
  "create_if_missing": true
}
```

---

### 4. `http_check`
Performs an HTTP/HTTPS health probe against an endpoint, expecting a specific status code within a timeout.
- **Allowed Phases:** `healthcheck`
- **Runs On:** Host
- **Parameters:**
  - `url` (string, required): Full HTTP/HTTPS URL to check.
  - `expected_status` (integer, optional): Expected HTTP status code (default `200`).
  - `timeout_seconds` (integer, optional): Maximum wait time per probe in seconds (default `5`).
  - `retries` (integer, optional): Number of retry attempts (default `3`).
  - `delay_seconds` (integer, optional): Delay between retries in seconds (default `2`).

```json
{
  "@action": "http_check",
  "url": "http://127.0.0.1:8080/health",
  "expected_status": 200,
  "retries": 5,
  "delay_seconds": 3
}
```

---

### 5. `shell`
Executes an arbitrary shell command.
- **Allowed Phases:** `host_prepare`, `container_startup`, `healthcheck`, `shutdown`
- **Runs On:** Context-dependent (Host or Container)
- **Parameters:**
  - `command` (string, required): Shell command string to execute.

```json
{
  "@action": "shell",
  "command": "python3 -m pip install -r requirements.txt"
}
```

---

### 6. `echo`
Outputs formatted log or status messages during lifecycle execution.
- **Allowed Phases:** All phases
- **Parameters:**
  - `lines` (array of strings, required): Log lines to print.

```json
{
  "@action": "echo",
  "lines": [
    "Container environment initialized successfully.",
    "Ready for incoming developer connections."
  ]
}
```

---

### 7. `install_preset`
Build-time layer injection hook for dynamically installing pre-configured packages.
- **Allowed Phases:** `image_prepare`
- **Parameters:**
  - `name` (string, required): Preset identifier from `presets.json` (e.g., `nodejs`, `llama-server`).
  - `version` (string, optional): Specific version string or constraint.

```json
{
  "@action": "install_preset",
  "name": "nodejs",
  "version": "18.x"
}
```
