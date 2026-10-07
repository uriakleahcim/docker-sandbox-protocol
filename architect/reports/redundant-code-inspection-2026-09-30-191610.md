# Redundant / Unnecessary Code Inspection Report

## Summary

- Report ID: `redundant-code-inspection-2026-09-30-191610`
- Created at: `2026-09-30T19:16:10Z`
- Repository: `/home/uriak/Work/AppSource/com.github/docker-sandbox-protocol`
- Branch: `main`
- Commit: `45960ab34faec856548857a935c74a8db73e6e14`
- Inspection scope: Active container declarations, groupings, generated local workspace/compose artifacts, runtime Docker inventory, and orchestration paths affecting those declarations
- Total findings: 11
- Safe removals: 3
- Safe inline candidates: 0
- Consolidation candidates: 1
- Lookup/cache candidates: 0
- Refactor candidates: 7
- Architect decision required: 0
- Unknown-usage findings: 0

## Inspection Method

The inspection compared the ignored active configuration against the tracked example configuration, mapped each declaration through `containers_cli.py`, searched repository references and documentation, inspected the generated host directories and compose file, and queried Docker for all actual containers. Removal classifications apply only to the local active profile and its empty generated artifacts unless stated otherwise. The tracked example catalog and documentation were evaluated separately because they demonstrate distinct harness postures.

Runtime evidence at inspection time:

- Docker contained `searxng` and unrelated Coolify containers, but no `dev-dev-sandbox`, `dev-restricted-agent`, `ai-ai-service`, or `web-stack` container.
- `/home/uriak/sandbox/workspace/{dev,restricted,ai,web-stack}` and matching scratch directories were empty.
- Those directories and `/home/uriak/sandbox/data/web` share the `2026-09-24 00:57` installer/setup timestamp.
- The active settings differ from the tracked examples only by the added SearXNG declaration and its services-group membership.
- The unused `agent-sandbox:latest` image occupies approximately 794 MB and was rebuilt while launching the custom SearXNG image.

## Execution Map

| Phase | Files / Symbols | Notes |
|---|---|---|
| Install/bootstrap | `install.sh:55-81`, `install.sh:84-87` | Copies every example declaration into active ignored configuration and creates generic sandbox roots. |
| Configuration load | `config/containers_cli.py:13-27`, `load_settings()` | Loads active JSON or falls back to the tracked example. |
| Target/default resolution | `get_default_container()`, `resolve_targets()` | The first grouping default makes bare `sandbox start` resolve to `dev-sandbox`. |
| Start validation | `main()`, `validate_all_settings()` | Validates lifecycle actions for every declaration, including inactive starter entries. |
| Image preparation | `main():1148-1150`, `do_build()` | Builds `agent-sandbox` for every start/rebuild before knowing whether the target uses a custom image or Compose. |
| Direct-container launch | `start_agent():620-839` | Applies mounts, limits, port bindings, and security to non-Compose declarations. |
| Compose delegation | `start_agent():639-662` | Delegates directly to Compose and returns before applying most declaration fields. |
| Status | `do_status():925-988` | Repeatedly shells out to Docker and interprets failed Docker access as absent containers. |

## Lookup Hotspots

| ID | Lookup | Location | Frequency | Risk | Recommendation |
|---|---|---|---:|---|---|
| LH-01 | Settings/groupings JSON reload | `load_settings()`, `get_default_container()`, `resolve_container_name()` | Multiple times per command | Low | Consolidate into one validated in-memory runtime model during CLI startup. |
| LH-02 | Docker existence/running checks | `is_container_running()`, `is_container_exists()`, `do_status()` | Multiple subprocesses per container per status/start | Medium | Return structured success/error states and fail visibly when the daemon is inaccessible. |

## Duplicate Logic Findings

| ID | Area | Files / Symbols | Problem | Recommendation | Classification | Risk |
|---|---|---|---|---|---|---|
| DL-01 | Active starter catalog | `config/containers_settings.json:5-159`; tracked example equivalent | The installed active profile retains all four sample declarations unchanged even though no corresponding runtime container or workspace content exists. | Keep the tracked examples, but reduce the active profile to actual local services. | `SAFE_CONSOLIDATE` | Low if group defaults are updated atomically. |

## Dead / Obsolete Code Candidates

| ID | Symbol | File | Evidence | Classification | Recommended Action | Risk |
|---|---|---|---|---|---|---|
| DR-01 | `dev-sandbox` active declaration | `config/containers_settings.json:5-50` | No Docker container; workspace and scratch are empty; definition exactly matches the sample; only docs/examples reference it. | `SAFE_REMOVE` | Remove from the ignored active profile and remove its empty local directories after the grouping/default update. Retain the tracked example and docs. | Low; bare `sandbox start` currently resolves here, so defaults must change in the same operation. |
| DR-02 | `restricted-agent` active declaration | `config/containers_settings.json:52-90` | No Docker container; empty workspace/scratch; unchanged sample declaration; no project-specific consumer. | `SAFE_REMOVE` | Remove from the ignored active profile and its empty directories. Retain as a useful tracked proxy-policy example. | Low. |
| DR-03 | `web-stack` local declaration and generated artifacts | `config/containers_settings.json:129-159`; `/home/uriak/sandbox/compose/docker-compose.yml`; empty `workspace/web-stack`, `scratch/web-stack`, and `data/web` | Declaration is disabled, no container exists, compose file is a generic nginx placeholder, and all bound content is empty. | `SAFE_REMOVE` | Remove from the active profile/grouping and delete only the confirmed-empty local placeholder artifacts if cleanup is authorized. Keep the tracked Compose example concept. | Low, provided ports 80/443 are not intended for future use. |

## Overlapping Abstractions

| ID | Abstractions | Files | Overlap | Recommendation | Classification |
|---|---|---|---|---|---|
| OA-01 | Example catalog versus active operational inventory | `*.example.json`, ignored active JSON, `install.sh` | Installation clones demonstration objects into the operational dashboard, so examples appear as intended services despite never being activated. | Initialize a minimal/empty active catalog or explicitly mark copied starters disabled; keep examples as templates. | `NEEDS_REFACTOR` |

## Unnecessary Complexity

| ID | Area | Files / Symbols | Complexity | Simpler Direction | Classification |
|---|---|---|---|---|---|
| UC-01 | Unconditional base-image build | `config/containers_cli.py:1148-1150`, `do_build()` | Every `start` and `rebuild` builds `agent-sandbox`, even when a declaration supplies `image` or `compose_path`. Launching SearXNG therefore created an unused 794 MB base image. | Build only for direct declarations without `image`, and only rebuild when explicitly requested or the base image is missing/stale. | `NEEDS_REFACTOR` |
| UC-02 | `ai-service` starter | `config/containers_settings.json:92-127`; `presets/presets.json:2-20` | The preset downloads a zip but never extracts/installs it; the startup lifecycle contains only `echo`, while startup script generation executes only `shell` actions. No inference process is launched despite the status message. | Remove it from the active profile. Repair the tracked example to install and launch a real service before advertising it as an AI service. | `NEEDS_REFACTOR` |

## Configuration Drift

| ID | Property / Config | Declared In | Consumed By | Gap | Recommendation |
|---|---|---|---|---|---|
| CD-01 | `toggle_logging`, `network.host_access.allowed_hosts` | Every sample/active declaration | No runtime consumer found in `containers_cli.py` | Dashboard/config imply logging and host allowlisting controls that do not exist. | Implement enforcement or remove/document the fields as reserved. |
| CD-02 | Compose declaration limits, mounts, network, and security | `web-stack` declaration | Compose branch only checks `compose_path`, container name, lifecycle, and invokes `docker-compose up -d` | `cpu_limit`, `memory_limit`, `workspace_path`, `scratch_path`, network posture, and sudo policy are displayed but not applied to the Compose stack. | Validate these values against Compose or reject unsupported fields for Compose-backed entries. |

## Metadata / Schema / Contract Drift

| ID | Metadata / Contract | Expected Use | Actual Use | Gap | Recommendation |
|---|---|---|---|---|---|
| MC-01 | `default_container` in every group | Select a default per group | `get_default_container()` returns the first default encountered globally; group-target resolution ignores each group's default | Only the development default affects bare commands, and it points to a redundant starter. | Define one explicit global default or make group-default semantics real; for this host, select `searxng` if bare start should manage the installed service. |
| MC-02 | Docker status contract | Distinguish absent containers from daemon/access errors | `is_container_running()` and `is_container_exists()` ignore command failures, producing `NOT CREATED` when Docker access is denied | Status can falsely validate redundancy without privileged runtime evidence. | Check subprocess return codes and report `DOCKER UNAVAILABLE` separately. |

## Recommended Refactor Packages

### Package 1 — Minimal Active Service Catalog

**Goal:** Keep only SearXNG in the ignored active profile while preserving all tracked examples.
**Files affected:** `config/containers_settings.json`, `config/container_groupings.json`, confirmed-empty paths below `/home/uriak/sandbox/`.
**Why:** Four sample declarations currently clutter operational status and three are enabled despite never being used.
**Risk:** Low if the default/grouping update is atomic and empty paths are rechecked immediately before removal.
**Verification:** Validate JSON, run `sandbox explain searxng`, inspect Docker inventory, and verify SearXNG remains reachable at loopback port 18080.

### Package 2 — Target-Aware Build and Status

**Goal:** Avoid unnecessary base builds and distinguish Docker errors from absent resources.
**Files affected:** `config/containers_cli.py`, CLI tests to be added.
**Why:** Custom images and Compose do not need `agent-sandbox`; silent daemon failures make the dashboard unreliable.
**Risk:** Medium because start/rebuild semantics are public CLI behavior.
**Verification:** Exercise missing-image, existing-image, custom-image, Compose, inaccessible-daemon, stopped-container, and running-container cases.

### Package 3 — Honest Starter Examples

**Goal:** Make sample declarations accurately demonstrate enforced behavior.
**Files affected:** example JSON, presets, README, specification, and tests.
**Why:** The AI example does not start inference, Compose fields are not enforced, and two advertised policy fields are unused.
**Risk:** Medium because examples define users' initial expectations.
**Verification:** Fresh-install smoke test followed by start/status/stop tests for each retained example.

## Proposed Architect Entries

- `architect/pending/2026-09-30-minimal-active-sandbox-catalog/`
  - Title: Reduce local active catalog to installed services
  - Reason: Implements DR-01, DR-02, DR-03, and MC-01 without touching tracked examples
  - Suggested files: `meta.json`, `brief.md`, `todo.md`, `context.md`
- `architect/pending/2026-09-30-target-aware-sandbox-runtime/`
  - Title: Make build and status target-aware
  - Reason: Implements UC-01 and MC-02
  - Suggested files: `meta.json`, `brief.md`, `todo.md`, `context.md`, `plan.md`
- `architect/pending/2026-09-30-repair-sandbox-starter-contracts/`
  - Title: Repair starter configuration and Compose enforcement contracts
  - Reason: Implements UC-02, CD-01, CD-02, and OA-01
  - Suggested files: `meta.json`, `brief.md`, `todo.md`, `context.md`, `plan.md`

## Verification Plan

- [ ] Run Python syntax compilation for the orchestrator and validators.
- [ ] Validate all active and example JSON files.
- [ ] Run lifecycle validation for every retained declaration.
- [ ] Run `sandbox status` with Docker available and unavailable.
- [ ] Verify direct image, generated image, and Compose start/stop paths separately.
- [ ] Confirm loopback/public port scopes from Docker inspection.
- [ ] Confirm SearXNG UI and JSON API remain operational.
- [ ] Recheck candidate directories are empty immediately before any deletion.
- [ ] Verify tracked examples and README remain coherent after any starter-contract changes.

## Findings Requiring Human Decision

No technical uncertainty remains about current usage. The owner still needs to authorize the cleanup package because it changes the active CLI catalog and removes local placeholder directories. A separate product decision is needed before changing tracked examples: whether fresh installs should begin with no active containers or with explicitly disabled demonstrations.

## Non-Findings / Things Intentionally Kept

- `dev-sandbox` and `restricted-agent` represent genuinely different security postures. They are redundant only in this host's active profile, not in the tracked example catalog.
- SearXNG is a live, validated service with persistent non-empty configuration and must be kept.
- Coolify containers are live but are not declared or owned by Docker Sandbox Protocol, so they are outside this cleanup scope.
- The existing `bin/sandbox` modification predates this inspection and was not altered.

## Final Notes

The safest next step is Package 1: remove the four starter entries from the ignored active profile, make SearXNG the sole services/default entry, and remove only the confirmed-empty starter directories and generic nginx compose placeholder. Do not delete the tracked `*.example.json` declarations merely because they are unused locally.
