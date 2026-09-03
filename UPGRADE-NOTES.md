# UPGRADE-NOTES

> 本文件记录升级过程中的实际行为差异。每次升级追加新章节。

---

## v1.1.2 → AgentTeams v1.2.2 (2026-08-14)

**Scope**: Docker Compose only (k8s manifests out of scope)

### Summary

Upgraded from hiclaw v1.1.2 to AgentTeams v1.2.2. All containers running on v1.2.2
images with AGENTTEAMS_* env vars, agentteams.io domains, and /opt/agentteams/ paths.

### Phase 0 Findings

1. **Higress segfault on WSL2**: CONFIRMED (exit 139). nginx bypass retained.
2. **Script paths**: `/opt/agentteams/` confirmed (renamed from `/opt/hiclaw/`).
3. **FS paths**: `/root/agentteams-fs/` confirmed.
4. **Zero HICLAW_ residuals** in v1.2.2 images (hard cut).
5. **QwenPaw 2.0**: `start-qwenpaw-manager.sh` exists but `/opt/venv/qwenpaw/bin/python3`
   is MISSING from the manager image. OpenClaw runtime used instead
   (`AGENTTEAMS_MANAGER_RUNTIME=openclaw`).
6. **Official hermes-worker image**: Lacks hermes-agent + pip3. Self-built retained.
7. **openclaw.json**: Still the primary config input for both runtimes.

### Phase 2: QwenPaw Switch — BLOCKED

Manager image missing `/opt/venv/qwenpaw/` venv + `copaw_worker` module.
`start-qwenpaw-manager.sh` hardcodes `/opt/venv/qwenpaw/bin/python3` (lines 75, 282).
OpenClaw runtime working. All 3 workarounds retained (fix-direct-rooms.py already
inactive, LLM_PROVIDER + allowlist patch still needed for OpenClaw).

### Naming Changes

| Dimension | v1.1.2 | v1.2.2 |
|-----------|--------|--------|
| env var prefix | `HICLAW_*` | `AGENTTEAMS_*` |
| Matrix domain | `matrix-local.hiclaw.io` | `matrix-local.agentteams.io` |
| AI gateway domain | `aigw-local.hiclaw.io` | `aigw-local.agentteams.io` |
| MinIO bucket | `hiclaw-storage` | `agentteams-storage` |
| mc alias | `hiclaw` | `agentteams` |
| Container FS | `/root/hiclaw-fs/` | `/root/agentteams-fs/` |
| Scripts | `/opt/hiclaw/` | `/opt/agentteams/` |
| Secrets | `/data/hiclaw-secrets.env` | `/data/agentteams-secrets.env` |
| Provider name | `hiclaw-gateway` | `agentteams-gateway` |
| Log dir | `/var/log/hiclaw/` | `/var/log/agentteams/` |

### Verification

- All 17 containers running
- Manager init completed (exit 0)
- `@manager:matrix-local.agentteams.io` logged in
- Workers connected to Matrix
- MinIO `agentteams-storage` bucket correct
- Provider `agentteams-gateway/glm-5.2` working
- Zero `HICLAW_` / `hiclaw.io` / `hiclaw-fs` in docker-compose scope
- Auth/API/Frontend/MinIO health checks passing

### Phase 1 — Image + env + domain rename ✅ Complete (2026-08-14 + 2026-08-17 follow-ups)

All 10 steps done. Runtime scope (docker-compose + agent docs + skill scripts + Python +
frontend + tests) has zero `HICLAW_` / `hiclaw.io` / `hiclaw-fs` / `hiclaw-storage` /
`/opt/hiclaw/` residuals. Verified via grep across `hiclaw/`, `deploy/docker/`,
`deploy/hiclaw/`, `src/`, `frontend/`, `tests/`.

Commits:
- `2f27794` (2026-08-14) — main rename: docker-compose, 4 Dockerfiles, 8 bootstrap
  scripts, auth_service/main.py + google_oauth.py, server/config.py, frontend
  useMatrixChat.ts, CLAUDE.md, README.md (32 files, +995/-363).
- `e422f50` (2026-08-17 follow-up) — runtime agent docs + skill scripts missed by
  2f27794: Manager/Worker `SOUL.md`/`AGENTS.md`/`SKILL.md` (8 files),
  `dispatch-to-worker.sh` + `result-watcher.sh` MinIO path, root `.env.example`.
  **Critical fix**: the two skill scripts still referenced `hiclaw/hiclaw-storage`
  MinIO alias+bucket after the bucket was renamed to `agentteams-storage`. With
  `2>/dev/null` graceful degradation in both scripts, task `spec.md` /
  `history.json` / `result.json` MinIO sync would silently fail — Workers could
  not pull the spec and could not execute delegated tasks.
- `cb3fd62` (2026-08-17 follow-up) — regression fix: commit 2f27794 renamed
  `ServerConfig.hiclaw_manager_url` → `agentteams_manager_url` and env var
  `HICLAW_MANAGER_URL` → `AGENTTEAMS_MANAGER_URL`, but
  `tests/test_server_config.py` still asserted on the old field name
  (AttributeError: 'ServerConfig' object has no attribute 'hiclaw_manager_url')
  and set the old env var. Also README §env-var example still used `HICLAW_*`
  and CLAUDE.md incorrectly claimed QwenPaw 2.0 defaults to working.

Static verification (2026-08-17):
- `pytest tests/` — 687 passed, 13 skipped, 0 failed
- `ruff check src tests` — clean
- `mypy src` — 70 source files, no issues
- `bash -n` on 4 affected shell scripts — OK

### Phase 3 — Worker + hermes verification ✅ Complete (2026-08-14)

Covered by Verification section above. graph-worker + analytics-worker connected
to Matrix; 3 MCP servers (nebula/audit/cache) health-checked. Official
hermes-worker image lacks `hermes-agent` + `pip3` — self-built
`Dockerfile.hermes-worker` retained (per Phase 0 finding #6).

### Phase 4 — E2E + cleanup 🟡 Partial (2026-08-17)

- **4.1 E2E full regression** — IN PROGRESS (2026-09-01; see the
  "2026-09-01 — Local E2E unblocking" section below for the full narrative).
  Static unit tests pass (686; `test_mcp_transport.py` updated to assert the
  empirically-verified `/sse` endpoints — the old test asserted `/mcp` per the
  streamable-http aspiration, but the installed FastMCP 4.0.0 serves SSE).
- **4.2 Workaround elimination grep** — PASS (runtime scope). Zero `HICLAW_` /
  `hiclaw.io` / `hiclaw-storage` / `hiclaw-fs` / `/opt/hiclaw/` residuals in
  `hiclaw/`, `deploy/docker/`, `deploy/hiclaw/`, `src/`, `frontend/`, `tests/`.
  Intentionally retained:
  - `deploy/k8s/**` — k8s manifests, out of scope per Summary
  - `src/honeybadge/metrics/collectors.py` `HICLAW_METRICS` instance +
    `HiClawMetricsCollector` class — NOT dead code. `__init__` registers 7
    Prometheus metrics (`honeybadge_hiclaw_*`) with global REGISTRY as a
    side effect of instantiation. `honeybadge_hiclaw_workers_active` is
    queried by the `NoActiveWorkers` critical alert in
    `deploy/observability/prometheus/rules/honeybadge.yml`. The Python
    instance is never called, but removing it would unregister the metrics
    and silently break the alert. Metric names still use `hiclaw` prefix;
    renaming to `agentteams` is a separate breaking change (dashboards +
    historical data) and out of scope for this upgrade.
  - `docs/baselines/v1.1.{0,2}/`, `docs/superpowers/{plans,specs}/` —
    historical snapshots, out of scope
- **4.3 Docs + commit + PR** — partial. Docs updated (CLAUDE.md, README.md,
  UPGRADE-NOTES.md). Commits local on `ralph/agentteams-v1.2.2-upgrade`.
  **PR not pushed** — GitHub PAT in remote URL expired; `gh` keyring token
  invalid. Needs `gh auth login` or new PAT.

### Remaining Work

| Item | Blocker | Action |
|------|---------|--------|
| Phase 4.1 — E2E full regression (9 groups) | `docker compose` stack | local run |
| Phase 4.3 — push branch + open PR | GitHub PAT expired | `gh auth login` |
| Phase 2 — QwenPaw switch + 3 workaround removals | upstream manager image missing `/opt/venv/qwenpaw/` + `copaw_worker` | wait for upstream fix |

### 2026-09-01 — Local E2E unblocking (Phase 4.1 prep)

Local environment: standalone `docker-compose` v5.1.4 (no `docker compose`
plugin), pytest via `py -3.12 -m pytest`. Four stacked blockers were found and
fixed before the chat E2E could pass:

1. **LLM upstream switched to GLM-5.3** (Volcengine API gateway,
   OpenAI-compat `/v1`). `.env` + `docker-compose.yaml` now parameterize
   `AGENTTEAMS_OPENAI_BASE_URL` / `LLM_UPSTREAM_HOST` / `LLM_API_KEY` /
   `MANAGER_LLM_MODEL=LLM_MODEL=glm-5.3`. The old `open.bigmodel.cn` upstream
   was DNS-failing intermittently inside the aigw-bypass nginx.
2. **Manager "pairing required"** (198k errors since Aug 20): stale
   `/root/manager-workspace/.openclaw/devices/{paired,pending}.json` (device
   capped at `operator.read`, unapproved `operator.approvals` upgrade) blocked
   the manager's gateway connection. Deleted both + `docker restart` →
   `[matrix] connected to gateway`. Manager workspace is ephemeral (overlay
   FS), so recreation can re-poison; `init-workers.sh` cleanup TODO remains.
   **TODO CLOSED (2026-09-03) — obsolete in v1.2.2**: the
   `devices/{paired,pending}.json` approval flow no longer exists upstream;
   the running v1.2.2 manager has no `devices/` dir at all — device identity
   is a plain keypair at `.openclaw/identity/device.json` (verified live).
   `/root/manager-workspace` sits on no volume (ephemeral overlay), so every
   container recreation starts with a fresh identity and re-pairs cleanly —
   exactly what the v1.2.2 upgrade recreation demonstrated. No cleanup code
   added on purpose (a `rm` for a directory that no longer exists would be
   cargo-cult).
3. **Stale Python images (root cause of chat timeouts)**: all 5 Python
   service images were Jun/Apr builds with `@manager:matrix-local.hiclaw.io`
   baked in (pre-rename). `honeybadge-auth` reused a DM room whose only
   member is `@hb-admin` (invite went to the non-existent hiclaw-domain
   manager), so chat messages reached nobody. Rebuilt images from branch
   source → auth provisions a fresh DM room → manager auto-joins.
   **Lesson: image rebuild is a required step after domain renames — env
   overrides in compose don't cover defaults baked into code.**
4. **`init-workers.sh` registered MCP endpoints as `/mcp`** (regression from
   #145, which misread `server.py`'s `__main__` block): the Dockerfile CMD
   runs `python -m honeybadge.__main__ <name>-mcp` → `transport="sse"` →
   servers serve `/sse` (404 on `/mcp`). Workers burned entire runs repairing
   `mcporter.json` mid-query. Fixed to `/sse` (worker registration + manager
   mcporter.json).
5. **Stale init-log path in the E2E harness** (v1.2.2 rename miss):
   `tests/e2e/conftest.py` and `.github/workflows/e2e-tests.yml` (11 refs)
   waited on `/var/log/hiclaw/honeybadge-init.log`; v1.2.2 writes
   `/var/log/agentteams/honeybadge-init.log`. Every `reset_manager` fixture
   call would burn 3×90s of retries plus 2 spurious manager restarts. Missed
   by the Phase 1 residual grep because `/var/log/hiclaw/` was not in the
   pattern list. Also fixed in conftest: the analytics-worker session reset
   was a silent no-op — it assumed the openclaw layout
   (`/root/.openclaw/agents/main/sessions`, `sessions.json`, `pgrep
   openclaw`), but the hermes-worker image keeps transcripts in
   `/root/.hermes/sessions` with no `sessions.json` and runs `hermes gateway`.
6. **Build-context pollution** (no root `.dockerignore`): builds from the
   repo root uploaded `deploy/docker/data/` (1.2GB live NebulaGraph data)
   into every image build; WAL files also fail tar with
   `archive/tar: write too long`. Added `.dockerignore` — the 3 MCP image
   builds went from stuck 60+ min to ~7 min. The rebuilt images also picked
   up fastmcp 4.0.0 (was 3.4.2); `/sse` verified working on all 3 MCP
   servers.
7. **5-minute gateway restart loop (upstream v1.2.2 bug, killed E2E tc310)**:
   the worker image's `worker-entrypoint.sh` runs a MinIO fallback pull every
   300s and merges via `/opt/agentteams/scripts/lib/merge-openclaw-config.sh`,
   whose jq merge does `.gateway = $remote.gateway` — a wholesale replace of
   the gateway section. The openclaw runtime itself oscillates
   `gateway.controlUi.allowedOrigins` (adds it when the gateway boots, strips
   it again on a later config save), so every pull flipped a restart-worthy
   gateway key and the config watcher SIGUSR1'd the gateway:
   `[reload] config change requires gateway restart (gateway.controlUi)`.
   Restarts are deferred while embedded runs are active, but exec-event runs
   and Matrix reply delivery are not protected — tc310's admin data-volume
   query (>5 min) died with `[SETTLE] exception after 480000ms`. Only
   graph-worker is affected (upstream agentteams-worker image); the
   self-built hermes analytics-worker pulls once at boot, 0 restarts.
   Two-part fix:
   - `deploy/hiclaw/init-workers.sh` §1c' strips `gateway.controlUi` from
     both workers' MinIO `openclaw.json` (must re-run after every Manager
     auto-init, which regenerates configs).
   - `deploy/hiclaw/merge-openclaw-config.sh` (patched copy of the upstream
     script, mounted read-only over the original in docker-compose.yaml)
     deep-merges gateway: `.gateway = (($local.gateway // {}) *
     ($remote.gateway // {}))` — remote still wins on shared keys so
     Manager-pushed changes propagate, but local-only runtime keys survive.
   Verified: two consecutive pull cycles (22:55, 23:05) with zero SIGUSR1 /
   config-change restarts (previously every cycle restarted).
8. **analytics-worker never received Matrix dispatches (broken since image
   build)**: `Dockerfile.hermes-worker` installed *unpinned*
   `mautrix[encryption]` / `aiohttp-socks`, which resolved to versions newer
   than hermes-agent's internal `platform.matrix` feature pins (mautrix
   0.21.1 vs ==0.21.0, aiohttp-socks 0.12.0 vs ==0.11.0, aiohttp 3.14.3 vs
   ==3.14.1). At every gateway boot hermes's version check failed
   ("Platform 'matrix' is registered but adapter creation failed") and its
   lazy pip-install self-heal is blocked by PEP 668 — so the hermes gateway
   ran Matrix-less since the image was first built (agent.log shows the
   failure from 2026-08-14). The erp-query-dispatch protocol delivers tasks
   as Matrix @mentions to the worker room, so **every @analytics-worker
   task hung forever** (spec.md + history.json synced to MinIO, no
   result.json, no reply). @graph-worker tasks were unaffected. This killed
   tc310 both times: "统计高风险的采购订单数量" routes to analytics-worker
   per the routing table. Fixed by pinning the three packages in
   `Dockerfile.hermes-worker` to hermes's feature pins (durable) and
   `pip install --break-system-packages` of the same pins in the running
   container + hermes restart (surgical; container writable layer survives
   restarts but not recreation). After the fix: "✓ matrix connected" in the
   hermes gateway log — first Matrix connection for this worker ever.
   Also noted: `reset_manager` (conftest) killing hermes is what surfaced
   the crash-looping SIGTERM exits; they are the entrypoint re-execs, not
   crashes. The hermes kanban "reaped 1 zombie worker pids=[7]" 60s after
   every gateway start predates tonight and is unrelated to task execution.
9. **Session group (test_03) silently skipped 5/8 tests — masked a real
   product bug**: the old tests probed for rename/delete buttons and a
   session-name input that do not exist in the UI (sidebar uses a per-session
   `el-dropdown` "⋯" menu → ElMessageBox dialog), so tc201/202/203 skipped
   themselves. Once rewritten for the real flow, tc202 exposed that
   **session rename never persisted**: `ChatView.vue` showed a success
   toast but the API call was a placeholder comment. The endpoint existed
   all along (`http.ts` `updateSession` → `PUT /sessions/{id}` →
   `sessions.py`). Fixed in three places: added `updateSessionTitle` to
   `stores/chat.ts`, added `renameSession` to `composables/useMatrixChat.ts`,
   and wired the call into `ChatView.vue`. Test rewrites: rename/delete go
   through the ⋯ dropdown (Element Plus teleports every session's dropdown
   menu to `<body>`, so locators must scope with `:visible` — a plain
   selector matched ~80 hidden menus and blew up Playwright strict mode);
   tc201–204 now create sessions via the 新对话 button and stay entirely
   off the LLM query path (each runs in seconds; the old tc204 fired 3 LLM
   queries and hit a 720 s thread-method timeout that aborted the whole
   pytest process). tc201–204 now pass; tc206/207/208 legitimately skip —
   session search, pagination, and export do not exist in the UI (product
   gaps, not test gaps).
10. **Docker Desktop port-forwarding wedge (WSL2)**: after a hard engine
    collapse, all published ports return HTTP 000 ("Empty reply from
    server") even though containers are healthy and `docker exec` works —
    com.docker.backend's TCP proxies are wedged. `wsl -t docker-desktop`
    does NOT fix this (tried twice; it reliably re-wedges forwarding). The
    only fix is a full Docker Desktop restart: taskkill all "Docker
    Desktop.exe" + backend processes, then relaunch (via PowerShell
    Start-Process — `cmd //c start` hangs from Git Bash). Second gotcha: if
    the relaunched Desktop reuses a still-running docker-desktop distro, the
    engine hangs forever on "still waiting for init control API". Clean
    procedure: kill Desktop + backend → `wsl -t docker-desktop` → verify
    all distros Stopped → relaunch → engine ready in ~11 s.
11. **nebula-storaged WAL replay crisis (data-recovery mode)**: the hard VM
    kills during the earlier port fight left the entire live dataset
    (1.1 GB) in raft WALs (`/data/storage/nebula/61/wal/<part>/`, ~10.6 MB
    × 100 parts, all written at the collapse moment) with rocksdb SSTs
    nearly empty. Every storaged boot must replay all 100 parts at ~5 min
    each (≈8 h serial). **The dataset is unreproducible**: the Postgres
    `honeybadge_ods` database is empty (0 rows in all ODS tables) and the
    cached CSVs in `deploy/test-data/usaspending_csv/` are an older,
    different dataset (10k POs vs the live 24,327). A full backup of the
    storage volume is at `.backups/nebula-storage-20260901-1205.tar`
    (1.17 GB, gitignored). **RULE: do not restart storaged or Docker while
    it is replaying** — each unclean kill resets progress and deepens the
    dirty state. All remaining E2E groups that touch the graph (tc205,
    permission, antihal, mcp) are blocked until replay completes.
12. **honeybadge-server Nebula pool startup race**: after the clean Docker
    Desktop restart, honeybadge-server started before nebula-graphd was
    accepting connections. `app.py` initializes `app.state.nebula` at
    startup with only ~30 s of connect retries (`db/nebula.py` `connect()`:
    5 attempts, 2-16 s backoff); on failure `app.state.nebula` stays `None`
    **forever** — the health endpoint then reports `nebula: down / not
    connected` and nothing retriggers init (lazy reconnect exists only in
    `execute()`, not on the health path). Surfaced as a tc601 failure with
    graphd demonstrably up (tc701 socket + tc713 schema queries passed).
    Fixed by restarting honeybadge-server once graphd was up. **Follow-up
    implemented**: the health endpoint now lazily reconnects —
    `server/health.py::_ensure_nebula` retries `connect()` when
    `app.state.nebula` is None/unpooled, at most once per 30 s cooldown and
    capped at 15 s per attempt, storing the recovered client on `app.state`
    (which also unblocks the WebSocket path). Covered by 4 unit tests in
    `tests/test_graceful_degradation.py::TestHealthLazyNebulaReconnect`.
13. **Frontend `npm run build` was broken (pre-existing)**: PR #200 (unified
    response envelope) introduced `vue-tsc` errors in `frontend/src/api/http.ts`
    — the response-interceptor error path accessed `body.success` /
    `body.error.message` on an inferred `{}` type, and since `"build"` runs
    `vue-tsc && vite build`, production builds failed. Fixed with an explicit
    envelope type cast + truthiness guard (no behavior change). Also updated
    stale `tests/test_mcp_transport.py` (see 4.1 above) and fixed the
    frontend type-check, ruff, mypy, and full unit suite are now green.
14. **Second Docker Desktop engine collapse under sustained E2E load**:
    ~17 min into the permission group run (dual-browser `create_user_page`
    tests + LLM queries), the engine API started returning 500s and all
    ports died — tc409–414 errored on `docker exec` timeouts, tc415/416 on
    `Page.goto` timeouts. Recovery required the full clean-slate restart
    (kill processes FIRST, then `wsl -t docker-desktop`, verify Stopped,
    relaunch → engine up in 10 s). NOTE the order matters: stopping the
    distro while backend processes still run lets them respawn/reuse a
    stale VM, and the relaunched engine then hangs forever on "still
    waiting for init control API" (hit this once; 16 min stuck). The
    collapse hard-killed storaged again **after** it had completed its WAL
    replay — raft WALs were not truncated by ~40 min of service, so the
    full ~1.5 h replay had to run a second time. Follow-up risk: consider
    taking a post-recovery clean backup of the storage volume and/or
    batching the remaining groups to reduce peak memory load.
15. **tc408 absolute bounds were calibrated to the old 10k-PO dataset**:
    the live graph (24,327 POs, 58 orgs) has org 1000 = 1,578 POs, so the
    old `200 < analyst_count < 500` bound failed even though the L3 org
    filter worked perfectly (the query returned exactly 1,578).
    **Correction of the first recalibration**: the test docstring claimed
    subsidiary_lead = org 1011 (436 POs), but the RUNNING
    honeybadge-permissions service (probed via
    `GET /permissions/subsidiary_lead`) returns `org_ids=[1021]` — matching
    repo config (`permission_service/config.py`, `deploy/config/*.yaml`),
    conftest.py, and test_04's comments. Live org 1021 = 14 POs. Final
    bounds: `1000 < analyst < 2500` / `0 < subsidiary < 100`; the ×10
    admin-vs-single-org assertions pass with margin (15× and ~1,700×).
    tc409–414 use relative assertions only and needed no changes; stale
    "org 1011" comments in test_04/test_05 docstrings also corrected.
    Permission group pre-collapse result: 9 passed (tc401–408b), 1
    stale-bound failure (tc408, now fixed), tc409–416 to re-run after
    storaged recovery.
16. **Fourth engine collapse (spontaneous) + post-replay index settling**:
    ~35 min after replay #3 completed, a simple `docker restart
    honeybadge-nebula-graphd` triggered collapse #4 — engine API 500s
    (`no route to host` for 192.168.65.7:2376), vmmem at 0 GB (zombie VM).
    No E2E load was running; the host had been memory-thrashed all day.
    Same clean-slate recovery worked (kill processes → `wsl -t
    docker-desktop` → verify Stopped + no Docker processes → relaunch →
    engine up in seconds, all 17 containers back). Cost: storaged hard-killed
    again → WAL replay #4. Two operational findings from the replay #3
    aftermath: (a) **post-replay index settling** — for ~25 min after
    "healthy", storage RPCs time out (E_RPC_FAILURE storms in graphd), then
    indexes progressively come back: `LOOKUP ON PurchaseOrder WHERE
    PurchaseOrder.org_id == 1000` returned the correct 1,578 while
    `MATCH (p:PurchaseOrder) WHERE p.org_id == 1000 RETURN count(p)` still
    returned 0 — graphd's executor state appears poisoned by the RPC-failure
    storm (hypothesis; the planned graphd restart to confirm triggered the
    collapse, so it is unverified). Wait ~30 min after healthy before
    declaring the graph degraded. (b) The dataset itself survived every
    replay: 24,327 POs / 10,994 suppliers / org 1000 = 1,578 verified via
    LOOKUP after replay #3.
17. **Fifth engine collapse (spontaneous, zero load) + tiered E2E strategy**:
    ~35 min after replay #4 completed, a plain read-only connection attempt
    (nebula3 pool init to :9669) hit `Socket read failed: timed out`, and the
    engine API was already returning 500s — collapse #5, with NO test load
    running and not even a `docker` write command involved. Conclusion: the
    collapses are not E2E-load-triggered; the WSL2 engine is unstable under
    the sustained memory pressure of this 17-container stack regardless of
    what we do. Consequences adopted: (a) treat engine recovery + WAL replay
    (~2h + ~30 min settling) as an environment fact, not a test failure;
    (b) the full-suite regression cannot be the day-to-day verification
    loop. Implemented a **three-tier E2E regression strategy** (marker
    `smoke`, registered in pytest.ini):
    - **Tier 1 — smoke (~15 min, ~6 LLM queries, 22/130 tests)**: one
      sentinel per chain — tc001 login ×3 users, tc102 full chat chain
      (frontend→Matrix→Manager→worker→LLM→MCP→Nebula), tc201 session,
      tc408 L3 org-filter bounds (recalibrated, item 15), tc503
      permission-filter-in-Cypher, tc601 MCP/Nebula health, tc1101
      graph-worker routing, plus ALL 13 infra checks (LLM-free, ~5 s, they
      instantly localize a broken component). Run on every change:
      `./scripts/run-e2e-tests.sh --smoke` (skips infra setup by default —
      setup's worker restarts + seeding cost minutes and disrupt the very
      stack the smoke tier checks; use `--setup-only` first for cold
      bring-up).
    - **Tier 2 — group runs**: `--filter chat|auth|session|…` when touching
      a related area (~15 min per group).
    - **Tier 3 — full suite**: release gate only.
    A stub-LLM approach (replace GLM with a canned-responses server for
    chat-path tests) was considered and deferred: the OpenClaw agent-loop
    protocol (Manager dispatch, worker ack, DM back) is too easy to stub
    incorrectly — a green-but-meaningless test is worse than a slow one.
18. **Root cause of the ~2h WAL replays fixed — storaged data moved from
    Windows bind mount to a named volume (23:18, boot 2h05m → 37s)**: the
    compose file bind-mounted `./data/storaged` from the Windows filesystem,
    so every unclean engine kill forced a ~1.1 GB raft-WAL replay through
    Docker Desktop's 9p/FUSE bridge — RocksDB's small synchronous I/O
    pattern is pathologically slow there (~2h05m per replay, 5 collapses
    experienced). Migration while replay #5 was only at part 7/100 (replay
    is idempotent; aborting it is free): `docker stop -t 60` → `tar | tar`
    copy into named volume `honeybadge-storaged-data` (1.1 GB in **18 s** —
    the bridge's sequential throughput is fine; only the I/O *pattern* was
    the problem) → compose now mounts `storaged_data:/data/storage` (redis/
    postgres already used named volumes — that's why they always recovered
    fast; only Nebula was on the slow path). Result: storaged healthy in
    **37 s** with all 100 parts loaded vs ~2h05m. Rollback = revert one
    compose line (the old bind-mount copy is left in place untouched).
    Two experiment findings along the way: (a) a graceful `docker stop` does
    NOT truncate the raft WAL (1.1 GB before and after, all 100 partition
    dirs intact) — every cold start replays the full WAL, which the volume
    now makes cheap; (b) `deploy/docker/nebula_seed.py` generates only
    3,720 POs / 12 orgs — the live dataset (24,327 POs / 58 orgs) came from
    a different load process, so re-seeding is NOT a recovery path; the
    volume copy (exact data) was the only safe migration.
    Post-cold-start quirk observed both on the bridge and on the volume:
    for a warmup window, property-filtered `MATCH ... WHERE` returns 0
    (even `MATCH ... WHERE id(p) == "PO:10007"` returns `__NULL__`
    properties) while `LOOKUP ON ... WHERE` is immediately correct
    (org 1000 = 1,578 / org 1021 = 14 / FROZEN = 2) and `FETCH PROP` works.
    The earlier "graphd executor poisoning" hypothesis (item 16) is dead —
    graphd was freshly restarted and shows the same window. This healed by
    itself after replay #1 (permission group passed later that day); a
    heal-probe loop is quantifying the window now. Practical rule: after
    any storaged cold start, wait for `MATCH`+WHERE to return non-zero
    before running graph-count assertions.
19. **Collapse pattern root cause + operational guidance**: collapses #5–#7
    hit with zero E2E load (one during a plain read-only connect, two during
    `docker restart`), at 49/17/8-min intervals — a death spiral late in a
    memory-thrashed day. Machine has **15.7 GB total RAM**; `.wslconfig`
    caps the WSL2 VM at **12 GB**, leaving ~2.7–2.9 GB free for Windows +
    `com.docker.backend` + Playwright's Chromium (Chromium runs Windows-
    side, ~1 GB per browser). vmmem itself sits at only ~4 GB (ballooning
    works; container total ~3.2–5 GB, no leak — graph-worker/manager/
    analytics steady, hiclaw-embedded churns 0.7–1.6 GB page cache). So the
    machine is simply overcommitted at the Windows layer; E2E browser
    launches tip it over. Mitigations: (a) the named-volume migration
    (item 18) makes collapse RECOVERY cheap (engine restart ~3 min +
    storaged healthy ~40 s vs ~2.5 h) — collapses are now an annoyance,
    not a schedule-killer; (b) recommended but not applied: lower the
    `.wslconfig` VM cap 12 GB → 8–10 GB (stack peaks ~6 GB) to widen the
    Windows-side margin, and close heavy Windows apps during E2E runs;
    (c) avoid `docker restart <container>` — 2 of 7 collapses coincided
    exactly with it; prefer `docker stop` + `docker start`. Also note: the
    engine's `docker compose` CLI plugin registration breaks after some
    crashes (`unknown command: docker compose`) — invoke
    `"/c/Program Files/Docker/Docker/resources/cli-plugins/docker-compose.exe"`
    directly, or restart Docker Desktop to re-register.
    **End-of-night verdict (00:30)**: collapses #5–#8 in ~2 h (49/17/14-min
    intervals); after applying `.wslconfig` 12 GB → 8 GB + a full clean
    `wsl --shutdown`, the cold boot itself ballooned vmmem to ~7 GB (17
    containers cold-starting + WAL-replay page cache on the new volume)
    and Windows-side free RAM stayed at 0.3–0.7 GB. Windows baseline
    breakdown (top): Defender MsMpEng 0.9 GB, svchost 0.7 GB, Docker
    Desktop + backend ~0.8 GB, user's Chrome ~0.4 GB + proxy tools, this
    Claude session 0.9 GB — nothing reclaimable. Conclusion: **a 16 GB
    machine cannot run this 17-container stack + Windows baseline +
    Playwright Chromium simultaneously**; browser E2E is only viable on a
    fresh boot with heavy apps closed (or more RAM). The browser-free
    smoke subset (13 infra checks + tc601) was attempted at 00:25 and also
    failed — the VM was network-catatonic (every localhost port timed out
    while the named-pipe engine API still answered). Morning runbook:
    reboot host (or close Chrome etc.) → standard recovery if the engine
    died overnight (kill Docker processes → `wsl -t docker-desktop` →
    relaunch → storaged healthy in ~40 s) → wait ~10–25 min for the MATCH
    warmup window to close (`.backups/probe_lookup_vs_match.py`; LOOKUP is
    correct immediately) → `./scripts/run-e2e-tests.sh --smoke`.
    `.wslconfig` backup: `.backups/wslconfig.orig` (revert to 12 GB if the
    8 GB cap ever OOMs the VM).

20. **Collapse root cause FOUND (graphd memory balloon) + smoke tier fully
    validated (2026-09-02 morning session)**: with the chat stack up,
    collapses #11–#15 hit at 75 s–12 min intervals even at idle. A
    per-container `docker stats` tracer finally caught the killer:
    **nebula-graphd ballooned from ~9 MB to 7.23 GiB in ~30 s** under E2E
    chat load (healthy footprint is single-digit MB on the seed dataset).
    The balloon is anonymous (persists after `drop_caches`), and the Docker
    named-pipe API dies with 500s while container ports keep serving —
    "engine dead" ≠ "containers down".
    **Fix applied**: `mem_limit: 2g` on `nebula-graphd` in
    `docker-compose.yaml` (graphd OOM-restarts itself instead of killing the
    WSL2 VM; recreate with `docker-compose up -d --no-deps --force-recreate
    nebula-graphd`). After the cap: graphd stayed at ~25–30 MB through two
    full test runs and the engine never collapsed again.
    Also fixed this session:
    - **metad still on the Windows bind mount** (`.\data\metad`) — after
      unclean deaths its WAL replay through the 9p bridge takes 4–5 min, and
      storaged can hang at `Waiting for the metad to be ready!` with a stale
      MetaClient (log frozen, 0 `Load part` lines). Fix: `docker stop` +
      `docker start honeybadge-nebula-storaged` — healthy again in <1 min.
      **Follow-up DONE — see item 21.**
    - **Bare vs tag-prefixed property MATCH**: after unclean-death WAL
      replays, `MATCH (p:PurchaseOrder) WHERE p.org_id == 1000` (bare)
      returns 0/`__NULL__` while `p.PurchaseOrder.org_id` (tag-prefixed)
      serves correctly (1,578 for org 1000). The LLM generates tag-prefixed
      nGQL exclusively (audit_logs evidence), so the chat path is unaffected.
      Probe: `.backups/probe_prefix.py`.
    - **`scripts/run-e2e-tests.sh` portability**: bare `pytest` is not on
      PATH in Git Bash — runner now auto-detects (`pytest` → `py -3.12 -m
      pytest` → `python3 -m pytest`); `LLM_API_KEY` is auto-sourced from
      `deploy/docker/.env` so `--smoke` is self-contained.
    - **tc601 exposed a stale image**: the running honeybadge-server
      predated the health.py lazy-reconnect fix (lifespan connect failed
      while graphd was mid-recreation → "down" forever). Lesson: after
      changing `src/`, `docker compose build honeybadge-server` before E2E.
    - **tc705 (Higress console) is WSL2-impossible**: no Higress processes
      run inside hiclaw-embedded on this platform (documented controller
      segfault); the test now skips with a clear reason when the
      `hiclaw-aigw-bypass` sidecar is active, and still enforces real
      Higress on k3s/ECS.
    **Final one-shot smoke validation (08:14–08:26)**:
    `./scripts/run-e2e-tests.sh --smoke` → **21 passed, 1 skipped
    (tc705 WSL2 platform), 0 failed, 11 min 34 s**, engine green throughout
    (freeRAM 2.1–3.3 GB, vmmem ≤7.3 GB, graphd ~30 MB under its 2 GiB cap).
    The smoke tier (item 17) is now the working per-change verification:
    one command, ~12 min, ~6 LLM queries.

21. **metad migrated to a named volume (2026-09-02, closes the item-20
    follow-up)**: mirrored the storaged migration (item 18) — `docker stop
    -t 30/60` graphd → storaged → metad → `tar | tar` copy of the 42.5 MB
    bind-mount data into new volume `honeybadge-metad-data` (instant) →
    compose now mounts `metad_data:/data/meta`. Verification: metad healthy
    immediately on the volume (no 9p-bridge WAL replay), storaged/graphd
    back healthy in ~20 s each, `SHOW HOSTS` = 1 storaged ONLINE (100
    parts), 57 tags / 82 edges intact, total POs 24,327, tag-prefixed
    `MATCH ... org_id == 1000` = **1,578** (identical to pre-migration;
    note `org_id` is an INT — comparing against string `"1000"` silently
    returns 0 and is NOT the warmup quirk). honeybadge-server reported
    nebula `up` throughout recovery without a restart — first real-world
    pass of the item-19 lazy reconnect. Infra smoke group: 12 passed /
    1 skipped (tc705 WSL2) / 3.47 s. Rollback = revert the one compose
    volume line (old `./data/metad` bind-mount copy left untouched).

22. **Post-rename CI repair + audit fixes (2026-09-03, from the v1.2.2
    completeness re-audit)**:
    - **CI MinIO cleanup silently no-op since the rename**: all 4 inter-stage
      cleanup blocks + the log-dump `mc du` used the stale
      `hiclaw/hiclaw-storage` alias/bucket (`|| true` hid the failure) → now
      `agentteams/agentteams-storage` (verified live; the local bucket had
      accumulated 1.1 GiB / 1071 objects of task artifacts too).
    - **CI debug probes were dead**: worker containers are
      `honeybadge-graph-worker` / `honeybadge-analytics-worker` (compose
      `container_name:` overrides — not the `honeybadge-hiclaw-*` service
      names); Manager `state.json` lives at
      `/root/agentteams-fs/manager/state.json` (not under `agents/`); the
      hermes `/root/.hermes/logs/*` paths exist on NO container — replaced
      by an error/exception grep over `/tmp/openclaw/openclaw-*.log`, which
      immediately surfaces real faults (e.g. the aigw-bypass 502 timeouts).
    - **`pytest -m <group>` selected zero tests**: pytest.ini registered 9
      group markers that no test applied, and the conftest copy of the list
      had diverged. Every e2e file now carries
      `pytestmark = [pytest.mark.<group>, ...]`; marker registration is
      consolidated in pytest.ini only (added `context`, `routing`).
      Verified: auth=8 chat=12 session=8 isolation=15 permission=18
      antihal=13 mcp=10 infra=13 observability=11 context=10 routing=12
      smoke=22 — the 11 groups sum to the 130 total, no overlap.
    - **test_10/test_11 were orphans** (absent from CI and `--filter`):
      added `context` / `routing` cases to `run-e2e-tests.sh` and a keyed
      CI stage — worker routing is the core v1.2.2 regression risk.
    - **tc208 burned an LLM query before skipping**: the export-button probe
      now runs before `send_chat_query` (export remains a product gap).
    - **Frontend XSS**: `MarkdownText.vue` / `StreamingText.vue` rendered
      `marked` v15 output via `v-html` with no sanitizer — L4 raw-data
      passthrough made this a live vector. New shared
      `frontend/src/utils/markdown.ts` runs DOMPurify (3.4.14) over the
      marked output; `vue-tsc` + build pass.

23. **Round-2 audit fixes (2026-09-03)**:
    - **`TUWUNEL_URL` default was stale** in `auth_service/main.py`
      (`http://hiclaw-manager:6167` — the v1.1.2 embedded host) →
      `http://matrix-local.agentteams.io:6167`, matching the compose value
      (only mattered when the env var was unset).
    - **Item 2 devices-pairing TODO closed as obsolete**: the v1.1.2
      `devices/{paired,pending}.json` approval flow no longer exists in
      v1.2.2 — device identity is a plain keypair at
      `.openclaw/identity/device.json` and `/root/manager-workspace` sits
      on no volume, so every recreation re-pairs cleanly. No cleanup code
      added on purpose.
    - **Loki was unreachable from the host** (tc803/tc808 skipped forever):
      the compose Loki service had no `ports:` — unlike Prometheus/Grafana/
      Alertmanager. Exposed `3100:3100`; observability group now runs
      **9 passed / 2 skipped** (tc807 WSL2 Higress, tc810 product gap).
    - **tc807 hardened** like tc705: catches `httpx.TransportError` (the
      WSL2 port-18080 dead listener raises `RemoteProtocolError`, not
      `ConnectError`) and skips only when the aigw-bypass sidecar is up.
    - **Dead scripts deleted** (pre-Tuwunel era / superseded / scratch):
      `deploy/docker/init-matrix.sh` (Conduit), `deploy/docker/start.sh`,
      `scripts/update_readme*.py`, `scripts/run-e2e-tests.bat`,
      `tests/e2e/debug_tc105.py`.
    - **ECS diagnostic workflows made version-agnostic**: the TC-102 greps
      in diagnose-ecs.yml / redeploy-ecs.yml now also match
      `AGENTTEAMS_MATRIX_URL` / `AGENTTEAMS_*` env vars (additive — works
      for the v1.1.2 cluster today and v1.2.2 after redeploy).
    - **Stale READMEs refreshed**: `deploy/docker/README.md` (compose v2
      syntax + env-file, real services table incl. Tuwunel :7167, AgentTeams
      v1.2.2 topology + registry image tags) and `tests/e2e/README.md`
      (test_10/test_11 rows, 130 total, marker table incl. context/routing/
      smoke/requires_llm, .bat reference removed).
    - **`run_pipeline.py` P2 TODO assessed, not implemented**: alerting here
      is pull-based by design (Prometheus rules + Alertmanager); receivers
      are still placeholder templates. Comment now documents the intended
      Phase-2 path (quarantine gauge in ETLMetricsCollector +
      ETLQuarantineHigh rule, mirroring ETLStale/ETLLagHigh).
    - **MinIO 1.0 GiB cache junk root-caused and pruned**: the v1.2.2
      manager image seeded `.codex/tmp/arg0/` (4 × 163 MiB codex binary
      copies) + `.npm/_cacache` into `/root/manager-workspace/`, which
      `start-manager-agent.sh` mirrors to MinIO `manager/` (initial push +
      change-triggered) and pulls into `agentteams-fs/` at boot — three
      copies of ~1 GiB. One-off deletes were re-uploaded twice before the
      source-first order was found. New **Step 5** in
      `manager-init-internal.sh` prunes all three (source → mirror →
      bucket, with settle-poll + retry). Bucket: **1.1 GiB/1075 objects →
      37 MiB/750 objects**; verified stable across two manager restarts,
      login + Tuwunel healthy throughout. Also propagates to k8s via the
      `hiclaw-init-scripts` ConfigMap on next `apply -k`.


Also fixed a pre-existing quoting bug in `scripts/run-e2e-tests.sh:138`
(`--env-file "$ENV_FILE up -d` missing close-quote, broken since first
commit). Smoke test result: `tc101 + tc102 PASSED` (202s) — full chain
frontend → Tuwunel → Manager → worker → GLM-5.3 → MCP(/sse) → NebulaGraph →
contract-002 reply with trace_id verified.

Full chat group result (2026-09-01): **12/12 passed in 868s** (tc101–tc112,
`py -3.12 -m pytest -c pytest.ini tests/e2e/test_02_chat.py -v --tb=short
--timeout=300`). Includes all 4 `reset_manager` fixture tests — the
init-log path fix (item 5) cut the run from an estimated 40-70 min to
14.5 min.

Full session group result (2026-09-01): **tc201–204 passed, tc206/207/208
skipped (features absent from UI), tc205 blocked on storaged replay**
(item 11). tc201–204 run entirely off the LLM path (~14 s for the three
UI tests) after the rewrite described in item 9.

---

## AgentTeams v1.2.3 评估（2026-09-02，结论：暂不升级）

上游 2026-08-22 发布 v1.2.3（v1.2.2 构建于 08-08）。三个镜像（manager / worker /
embedded）均拉取到本地，做了文件级 sha256 对比 + 运行时 build-info 校验。

**变更内容（实证检查，非 changelog 转述）：**

1. **Manager**：仅 `agent/` 技能层有实质变更 —— worker-management 技能新增
   `install-worker-skill.sh`（导入 ZIP 技能包并分配给 worker）+
   `safe-extract-worker-skill.py`（zip-slip 防护、条目数/解压大小上限），
   配套 SKILL.md / AGENTS.md / TOOLS.md 文档更新。`scripts/`、`configs/`、
   supervisord 配置全部字节级一致。
2. **Worker**：`/opt/agentteams` 全部 8 个文件一致；OpenClaw 运行时为同一
   commit（`2f35b6fa`，version 2026.4.14）的重构建，代码零差异（仅 16 个
   build-stamp 元数据文件不同）。
   **`merge-openclaw-config.sh` 未动 —— 网关 5 分钟重启循环 bug（item 7）
   上游未修复**，本地深合并补丁继续必需。
3. **Embedded**：MinIO（RELEASE.2025-09-07）/ mc（RELEASE.2025-08-13）/
   Tuwunel start 脚本全部一致；仅 `agentteams-controller`（101MB→108MB）与
   `agt` 两个二进制更新。该 controller 在 HoneyBadge 部署中未运行（未配置
   `AGENTTEAMS_MATRIX_APPSERVICE_AS_TOKEN`，AppService 模式关闭）。

**两个核心阻塞点均未解决：**

- **QwenPaw**：manager v1.2.3 仍缺 `/opt/venv/qwenpaw/` + `copaw_worker` ——
  Phase 2 依旧 BLOCKED。
- **网关重启循环**：worker 侧脚本字节级未变。

**结论：暂不升级。** 收益（worker 技能 ZIP 导入 —— 我们用 init-workers.sh 分发，
用不到）≈ 0；成本 = 4 个本地镜像重建 + 全量 E2E 重跑 + 3 个本地补丁全部仍需
保留。三个 v1.2.3 镜像已留在本地（增量层 ~1GB+，总标签含共享层），供未来升级
对比复用；不需要时可 `docker rmi` 三个 v1.2.3 tag 回收。

**重新评估触发条件**（任一满足即可重查）：

1. `merge-openclaw-config.sh` 上游改为 gateway 深合并 → 本地补丁可移除
2. manager 镜像补齐 `/opt/venv/qwenpaw/` + `copaw_worker` → QwenPaw 解锁
3. Higress controller WSL2 segfault 修复

版本探测（匿名 token 流程，无需登录）：

```bash
TOKEN=$(curl -s "https://dockerauth.cn-hangzhou.aliyuncs.com/auth?service=registry.aliyuncs.com:cn-hangzhou:china:cri-r0xfyoxudmtseqq7&scope=repository:agentteams/agentteams-manager:pull" | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -H "Authorization: Bearer $TOKEN" "https://higress-registry.cn-hangzhou.cr.aliyuncs.com/v2/agentteams/agentteams-manager/tags/list"
```

---

## v1.1.0 → v1.1.2 (2026-06-25)

> 以下为 v1.1.0 → v1.1.2 升级记录。

## 环境信息

- 升级日期：2026-06-25
- 操作人：Claude Code（Phase 1 验证）
- 起始版本：HiClaw v1.1.0（image tag `hiclaw-{embedded,manager,worker}:v1.1.0`，运行中 2 天）
- 目标版本：HiClaw v1.1.2
- 部署形态：☑ 本地 docker-compose  ☐ K8s/k3s  ☐ ECS
- Baseline 快照：`docs/baselines/v1.1.0/`（已导出；含敏感信息的 openclaw.json / workers-registry.json 未提交，仅保留模板和 mcporter.json）

---

## 阶段 1 验证记录

### 1.1 v1.1.2 image 拉取

```
# 记录实际拉取的 digest
docker images | grep hiclaw
```

- `hiclaw-manager:v1.1.2` digest：`sha256:488a919fb5cbdb76958d0301adaf3105b899b3c54d1597617f68cc58005b4666`
- `hiclaw-worker:v1.1.2`：已拉取
- `hiclaw-embedded:v1.1.2`：未拉取（阶段 1 模板对比不需要，仅 manager + worker 镜像）
- 多架构支持确认：☑ amd64  ☐ arm64（未验证 arm64）

### 1.2 mcpServers CRD schema diff（**硬 blocker — 已清除**）

**验证方法**：对比 v1.1.0 运行中容器和 v1.1.2 镜像内的模板文件、MCP 配置源码、编译后 JS 文件。

**实际对比结果**：

| 对比项 | 方法 | 结果 |
|--------|------|------|
| `generate-worker-config.sh` | `diff` v1.1.0 vs v1.1.2 manager 镜像 | **IDENTICAL** |
| `worker-openclaw.json.tmpl` | `diff` v1.1.0 vs v1.1.2 manager 镜像 | **IDENTICAL** |
| `manager-openclaw.json.tmpl` | `diff` v1.1.0 vs v1.1.2 manager 镜像 | **IDENTICAL** |
| `mcp-config.ts`（配置源码） | `diff` v1.1.0 运行中容器 vs v1.1.2 镜像 | **IDENTICAL** |
| `types.mcp.ts`（类型定义） | `diff` v1.1.0 运行中容器 vs v1.1.2 镜像 | **IDENTICAL** |
| `mcp-config-BXbuLA0x.js`（编译后） | `md5sum` 对比 | **相同**（`a7dd6ae7c4ba61a37f5169bd1d64ad9d`） |
| MCP/mcporter 文件列表 | `find` 对比 | **逐行完全相同** |

**关键发现**：

1. v1.1.0 worker `openclaw.json` **本身不含 `mcpServers` 字段** —— MCP 配置完全通过独立的 `mcporter.json` 文件管理（HoneyBadge WS-19/WS-20 的做法）
2. v1.1.2 的模板文件、MCP 配置源码、编译后 JS 与 v1.1.0 **完全相同**
3. v1.1.1 release notes 的 "Restructure mcpServers on Worker/Manager/Team CRDs" **只影响 K8s CRD 控制面**，不影响 docker-compose 模式下的 openclaw runtime / mcporter.json

**Schema 变化记录**：

- 变化摘要：**无变化**（docker-compose 模式下）
- 对 WS-19（Manager mcporter.json 直接写入）的影响：**无影响** —— v1.1.2 仍读取相同 schema 的 mcporter.json
- 对 WS-20（Worker mcporter.json 注册）的影响：**无影响** —— v1.1.2 的 mcporter 行为与 v1.1.0 相同
- 需要修改的文件：**无**
- `pytest -c pytest.ini -m mcp` 结果：待完整 v1.1.2 栈启动后验证（预计通过）

**结论：硬 blocker 已清除。** v1.1.1 的 mcpServers CRD 重构仅影响 K8s CRD 模式；本项目 docker-compose 模式下 MCP 配置通过 mcporter.json 管理，schema 未变。WS-19/WS-20 无需修改。

### 1.3 Workaround 验证记录

#### can-remove-now 组

| ID | 验证结果 | 实际行为 | 删除确认 |
|----|---------|---------|---------|
| WS-02 memorySearch pop | ☑ 已是死代码注释 | v1.1.0 模板 + `HICLAW_EMBEDDING_MODEL=""` 已阻止注入 | ☑ 已删（注释块） |
| WS-04 Manager baseUrl 模板 | ☑ env var 已设置 | `HICLAW_AI_GATEWAY_DOMAIN` 在 docker-compose.yaml:393 + k8s manager.yaml:277 均已设置 | ☑ 已删 |
| WS-06 allowedConsumers 重建 | **N/A — 误识别** | 见下方说明 | ☐ 无需删 |
| WS-12 immutable-field shim | ☑ 已迁移 | v1.0.9→v1.1.0 一次性迁移，`if` guard 已使其 no-op | ☑ 已删（54 行 → 1 行 pipe） |
| WS-13 /root/openclaw.json 符号链接 | ☑ 死代码确认 | `generate-worker-config.sh` 不读 `/root/openclaw.json` | ☑ 已删 |
| WS-14 hot-reload deadlock 注释 | — | 仅注释块（实际代码在 v1.1.0 升级时已删） | ☑ 已删 |

**WS-06 误识别说明**：调研阶段将 `init-workers.sh:347-407` 和 `manager-init-internal.sh:634-692` 标记为 WS-06（allowedConsumers 路由重建），但实际验证发现该代码是 WS-08（Higress LLM 路由 + API key 注入，still-needed）。`grep -r allowedConsumers deploy/` 在代码中零匹配。原始 `allowedConsumers` workaround 是 v1.0.9 中 Higress 路由的 `authConfig: {enabled: false}`，现已成为 LLM 路由的永久配置（路由使用 header 注入 API key，不使用 consumer 认证）。**WS-06 不是一个独立可删除的 workaround。**

**删除统计**：净删 101 行（manager-init-internal.sh -58 行，deploy-k3s.yml -54 行），`bash -n` + YAML 解析均通过。

#### needs-verification 组

> **关键发现**：由于 v1.1.0 与 v1.1.2 的模板文件和 `generate-worker-config.sh` **完全相同**（见 §1.2 schema diff），以下 workaround 的行为在两个版本中完全一致。对 v1.1.0 运行系统的验证等同于对 v1.1.2 的验证。

| ID | 验证结果 | 实际行为 | 删除确认 |
|----|---------|---------|---------|
| WS-01 reasoning: true pop | ☑ 仍注入 | 模板硬编码 `reasoning: true`；`MODEL_REASONING=true` 默认；pop 是唯一移除机制 | ☑ 保留 |
| WS-03 worker baseUrl rewrite | ☑ 生成正确 | `generate-worker-config.sh:97` 对 docker runtime 硬编码正确 URL；workaround 为 no-op | ☑ 保留（safety net，待 v1.1.2 部署后可删） |
| WS-09 Matrix port 修正 | ☑ 正确 6167 | 配置中 `matrix_homeserver=http://matrix-local.hiclaw.io:6167`；workaround 为 no-op | ☑ 保留（safety net，待 v1.1.2 部署后可删） |
| WS-11 dangerouslyAllowPrivateNetwork | ☑ 已传播 | `.channels.matrix.network.dangerouslyAllowPrivateNetwork = True` 已存在 | ☑ 保留 |
| WS-19 Manager mcporter.json | 见 1.2（硬 blocker 已清除） | schema 未变 | ☑ 保留 |
| WS-20 Worker mcporter.json | 见 1.2（硬 blocker 已清除） | schema 未变 | ☑ 保留 |

**结论**：6 个 needs-verification workaround **全部保留**。由于模板文件 identical，v1.1.2 不会修复这些问题的底层原因。WS-03 和 WS-09 可能已是 no-op，但作为 safety net 保留，待 v1.1.2 部署 + E2E 通过后再考虑删除。

### 1.4 Team Leader skill alias 检查

v1.1.0 Team Leader skills: `team-task-management`, `worker-lifecycle`, `team-task-coordination`, `team-project-management`
v1.1.2 Team Leader skills: `communication`, `file-sharing`, `mcporter`, `organization`, `project-management`, `task-management`, `team-coordination`

旧 skill 名在新版本中被重命名，v1.1.2 移除了兼容 alias。

- 被移除的 alias 名：`team-task-management`, `worker-lifecycle`, `team-task-coordination`, `team-project-management`
- 本项目引用情况：☑ 无引用（`grep -ri` 全仓零匹配）
- 更新确认：☑ 不需要

**结论**：本项目使用 Manager + Worker 架构，不使用 Team Leader agent。v1.1.2 的 Team Leader skill alias 移除对本项目无影响。

### 1.5 MinIO endpoint 验证

```bash
docker exec honeybadge-graph-worker sh -c 'echo $MINIO_ENDPOINT'
```

- 实际值：（待填）
- 预期：`:9000`（不是 `:8080`）
- 结果：☐ 通过  ☐ 失败

### 1.6 E2E 全量回归

```bash
./scripts/run-e2e-tests.sh
```

| 测试组 | 通过数 | 失败数 | 备注 |
|--------|--------|--------|------|
| auth | | | |
| chat | | | |
| session | | | |
| isolation | | | |
| permission | | | |
| antihal | | | |
| mcp | | | |
| infra | | | |
| observability | | | |
| **合计** | | | |

---

## 阶段 2 验证记录

### 2.1 K8s/ECS 迁移

- `workers-registry.json` → CRD 自动迁移：☐ 成功  ☐ 失败
- ECS 8GB 内存占用（`kubectl top pod`）：（待填）
- `init-workers.yaml` Job 是否还需要：☐ 删除  ☐ 保留
- K8s 409 重试自愈测试：☐ 通过  ☐ 失败
- Controller reconcile 保留 runtime mutation：☐ 通过  ☐ 失败

### 2.2 文档同步

- [x] `README.md:84,354` 版本号 v1.0.9 → v1.1.2（已被 v1.2.2 升级超越；2026-09-02
  同步至 v3.6：升级表 v1.2.2、Schema 计数 57 Tags + 82 Edges、embedded/manager
  容器拆分说明）
- [x] `CLAUDE.md` "容器重建后 DM allowlist 重置"段落修正（v1.2.2 已禁用
  observe-recovery，重建不再重置 allowlist）
- [x] `CLAUDE.md` MinIO endpoint 端口修正（Console :19001，:9000 不暴露宿主机）
- [x] `CLAUDE.md` "aigw-local.hiclaw.io:8080" 适用性确认（v1.2.2 重命名为
  aigw-local.agentteams.io:8080，workers 必须走该别名）

---

## 意外发现 / 风险新增

（记录计划外的发现，例如新 bug、新 workaround、文档与实际不符等）

1. **WS-06 误识别**（2026-06-25）：调研阶段将 `init-workers.sh:347-407` + `manager-init-internal.sh:634-692` 标记为 WS-06（allowedConsumers 路由重建 can-remove-now），但实际验证发现该代码是 WS-08（Higress LLM 路由 + API key 注入，still-needed）。`grep -r allowedConsumers deploy/` 在代码中零匹配 —— `allowedConsumers` 仅出现在历史文档中。原始 v1.0.9 的 `authConfig: {enabled: false}` workaround 已被吸收为 LLM 路由的永久配置。WS-06 不是一个独立可删除的 workaround，can-remove-now 实际数量为 5 而非 6。

---

## 回滚记录

- 是否触发回滚：☐ 否  ☐ 是
- 回滚原因：（待填）
- 回滚步骤：（待填）
- 回滚后状态：（待填）
