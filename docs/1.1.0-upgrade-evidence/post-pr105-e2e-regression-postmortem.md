# Post-PR-105 E2E regression postmortem and redesign plan

**Date**: 2026-05-16 02:03 – 03:42 UTC
**E2E run**: [25949974577](https://github.com/xiaohanarch/HoneyBadge/actions/runs/25949974577)
**Affected change**: PR #105 — `send_query_on_page` two-stage Manager-ack → Worker-data wait
**Action taken**: Reverted via PR #106 (merged 03:42 UTC)

## Scoreboard regression

| Run | Failed | Passed | Skipped | Δ passed vs baseline |
|---|---|---|---|---|
| Baseline (run 25910486244) | 77 | 20 | 9 | — |
| Post-PR-100 first | 66 | 31 | 9 | +11 |
| Post-PR-100 second | 73 | 28 | 5 | +8 |
| Post-PR-103 (best so far) | 50 | 44 | 12 | **+24** |
| **Post-PR-105 (regression)** | **76** | **20** | **7** | **0** (run timed out) |

Net change from post-#103 to post-#105: **-24 passed, +26 failed**. Total tests executed: 103 vs 106 (3 tests killed by 90 min `command_timeout` before pytest could print summary).

## What PR #105 did

Added a `_wait_for_worker_data_response` helper and modified `send_query_on_page` to perform a two-stage wait:

1. Wait up to `timeout` for ANY new assistant message (Manager dispatch ack)
2. Then wait up to `max(timeout, 60000)` ms for a message containing a `.data-collapse` or `.cypher-collapse` block (Worker structured response)
3. `try/except` fallback if the Worker response never arrives → caller reads `.last`

## Why it backfired

1. **Compound timeout per call**: when the Worker is throttled by DashScope quota and never sends structured data, each `send_query_on_page` call burns the full Stage-2 timeout (up to 60s) before falling back. 49 callsites × ~5s extra median + several × 60s pathological cases easily added ~8 min cumulative.
2. **90-min ECS `command_timeout`**: the GitHub Action's `command_timeout: 90m` kills the entire SSH command. Pytest gets SIGKILL'd before printing its summary line. The remaining unrun tests (~3) are silently lost.
3. **Fallback does not help**: when the timeout DOES fire, the caller still reads `.last` = Manager ack = wrong content. The assertion still fails, and we just took 60s longer to fail.
4. **Test backend regressed independently**: tests using `send_query_and_get_response` (TC-102, TC-105, TC-109, TC-112) — which PR #105 did NOT modify — also started failing. The 02:00–03:00 quota window was likely already partially exhausted from prior runs. PR #105 only made the slowdown worse.

## Lessons

- **A "harmless fallback" can still be lethal under a hard cumulative timeout.** Skip-with-reason is safer than wait-then-fall-back when the failure mode is "the backend is down."
- **Test infra changes need to be measured against suite wall-clock, not just correctness.** A change that makes the suite 10% slower past the CI timeout is worse than the bug it fixes.
- **Consecutive E2E runs degrade.** Possibly Tuwunel state accumulation, Worker memory pressure, or — most likely — DashScope hourly quota consumed by the previous run still affecting the current hour. The 02:00–03:00 quota window probably never had a full ~80% fresh allowance.

## Redesign plan

The empty-response bug is real (TC-303 captured `"Response: 助手\\n好的，我已经将您的查询请求发送给graph-worker..."`). But the fix must NOT cost wall-clock when the Worker is offline.

Two-step redesign:

1. **In the helper**: instead of waiting 60s then falling back to `.last`:
   - Wait up to ~15s for a Worker data message
   - If absent, inspect `.last` text for the Manager-ack signature (`已转发给.*worker.*任务 ID`)
   - If it IS the ack → `pytest.skip("worker_outage: only Manager ack received within deadline")` rather than asserting on it
   - This skips the test cleanly instead of timing out and failing

2. **In the test harness**: track skip-with-reason="worker_outage" separately from intentional skips so the scoreboard reflects "backend was sick" vs "test would have failed."

Deferring this redesign until:
- (a) the quota story is resolved (user decision on quota upgrade / 2nd API key / vendor diversification), OR
- (b) we can prove the fix in a fresh quota window where Worker is healthy

## Open questions for user

1. **Quota decision is unchanged from post-PR-100 finding**: still need one of {quota upgrade, second API key, second vendor} to make consecutive E2E runs stable.
2. **Functional failures persist** (trace_id missing, empty assistant responses, Matrix room provisioning) — these are real product bugs that the test helper redesign will EXPOSE rather than fix. They need backend-side investigation, which is out of scope until the test infra reliably distinguishes "backend bug" from "backend outage."

## Current state

- Master HEAD: `3739fff` (revert PR #106 merged)
- conftest.py: back to post-#103 state, no two-stage wait
- Expected next E2E result if rerun in a healthy quota window: ~44 passes (post-#103 baseline)
- Recommend NOT rerunning until quota is fresh + functional bugs investigated
