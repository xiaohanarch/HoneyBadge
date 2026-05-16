# Post-PR-103 E2E milestone — best result yet, but quota is no longer the dominant cause

**Date**: 2026-05-16 00:32 – 01:54 UTC
**E2E run**: [25947952428](https://github.com/xiaohanarch/HoneyBadge/actions/runs/25947952428)
**Deployed change**: PR #103 — `maxConcurrent` and `subagents.maxConcurrent` 8 → 4 on both workers.

## Scoreboard

| Run | Failed | Passed | Skipped | Δ passed vs baseline |
|---|---|---|---|---|
| Baseline (run 25910486244) | 77 | 20 | 9 | — |
| First post-PR-100 (maxConcurrent=8) | 66 | 31 | 9 | +11 |
| Second post-PR-100 (8, after quota wait) | 73 | 28 | 5 | +8 |
| **Third — post-PR-103 (maxConcurrent=4)** | **50** | **44** | **12** | **+24** |

Best result of the autonomous loop. Passed count more than **doubled** from baseline.

## Deployment correctness verified

Diagnose 25947878420 confirms both worker pods now hold `maxConcurrent: 4` and `subagents.maxConcurrent: 4`. A prior diagnose (25947714985) caught a race condition where the first redeploy let workers restart in parallel with the Manager pod, so workers fetched the still-old MinIO bundle before Step 2b finished patching. A second `Redeploy ECS` run cleared the race — MinIO already held the patched bundle from the prior cycle, so workers picked up `4` on first boot.

## Quota is still hit, but it is no longer the primary failure cause

Worker logs show DashScope `429 hour allocated quota exceeded` starting at **01:40 UTC**, ~68 minutes into the run. So:

- Tests that ran **before 01:40** failed **without** quota involvement — these are real product bugs.
- Tests that ran **after 01:40** are still dragged down by `failoverReason=rate_limit decision=surface_error`.

Rough split of the 50 failures by wall-clock vs the 01:40 quota boundary:

| Time window | Approx failed count | Likely cause |
|---|---|---|
| 00:33 – 01:40 (pre-quota) | ~42 | Functional product issues |
| 01:40 – 01:54 (post-quota) | ~6–8 | DashScope 429 rate-limit |

Halving concurrency successfully **delayed** quota exhaustion (first run hit it earlier) but did not eliminate it. Aggregate per-key token use across an entire E2E run still exceeds the hourly budget.

## Functional failure clusters (pre-quota)

Looking at the early failures by symptom:

1. **No trace ID in response** — `test_tc102_send_query_receives_response_with_trace`, `test_tc107_trace_id_format`, `test_tc505_l5_trace_id_displayed`, `test_tc507_l5_trace_id_audit_api`. The L5 audit chain is not surfacing `trace_id` to the frontend in this build.
2. **Empty / placeholder responses** — `test_tc303_cross_org_data_isolation` and several siblings assert `Admin should see PO data. Response: 助手` — the captured response text is literally just the speaker label `助手` (assistant) with no body. Suggests the chat returned an empty assistant turn.
3. **Data isolation gives 0 records** — `test_tc304_subsidiary_cannot_see_parent_org` got `0` records where ~337 expected. Could be permission/Cypher filter issue or empty-response side effect.
4. **Matrix room ID missing** — `test_tc308_matrix_room_isolation` reports admin has no Matrix room. May be Matrix provisioning regression.
5. **Permission tests across the board** — `test_tc401`–`test_tc414` block. Many derive from the same root cause as cluster 2 above (empty assistant responses make later assertions vacuous).
6. **Antihal / MCP** — `test_tc504`, `tc511`, `tc608`, `tc609`, `tc610` — various.

`test_tc603_cache_mcp_healthy` continues to fail with `Connection refused localhost:6379`; unrelated test-runner-local issue, predates this work.

## Recommendation to user

Two distinct workstreams are now unblocked:

1. **Functional bug investigation** (autonomous loop *can* tackle this)
   - Triage cluster 1 (`trace_id` plumbing) — narrow scope, deterministic
   - Triage cluster 2 (empty assistant responses) — likely the dominant cause, would unblock many tests at once
   - These do not require credentials or billing decisions
2. **Quota tail** (needs user decision)
   - Same three options as before: quota upgrade / second API key / further concurrency reduction
   - But yields diminishing returns now that quota only causes ~15% of failures

Suggested order: investigate (1) first; the user can decide (2) in parallel.
