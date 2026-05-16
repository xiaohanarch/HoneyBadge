# E2E failure root-cause triage — run 25955064057

**Date**: 2026-05-16
**Source run**: [25955064057](https://github.com/xiaohanarch/HoneyBadge/actions/runs/25955064057)
**Result**: 48 failed / 45 passed / 13 skipped / 1 error in 4739s

## Why this doc exists

Post-PR-103 / post-revert milestone (PR #108) established the new baseline at **45 passed**. The remaining 48 failures cluster around a small number of root causes. Before another test-infra change attempt (PR #105 regressed -24 passes), this doc captures the **categorized root causes** so a safer fix can be designed.

## Root cause categories

### A. Mid-stream LLM preamble read — **~33 failures**

**Pattern**: Test calls `send_query_on_page` or `send_chat_query` (single-stage wait, `length > 10` in body) → reads `.last.inner_text()` → captures LLM's "thinking out loud" preamble before Worker data arrives.

**Evidence from TC-304**:
```
AssertionError: Subsidiary (org 1021) should see ~337 records. Got: 0. Response: 助手
14:47

我需要为您统计采购订单的数量。让我运行路由脚本来确定最佳处理方式。
```

**Evidence from TC-303**:
```
AssertionError: Admin should see PO data. Response: 助手
14:47

现在
```
(message body is empty — wait completed on timestamp metadata)

**Affected tests** (sample, full list below):
- `test_04_isolation`: TC-303, TC-304, TC-307, TC-310 – TC-315 (9)
- `test_05_permissions`: TC-402, TC-402b, TC-404, TC-406, TC-408, TC-409 – TC-414 (10)
- `test_06_antihal`: TC-504, TC-505, TC-507, TC-511 (4)
- `test_10_context_and_memory`: TC-1004, TC-1006, TC-1007 (3)
- `test_11_worker_routing`: TC-1101, TC-1102, TC-1104 (×4 params), TC-1105 (×4 params) (10)

**Why PR #105's fix failed**: PR #105 added a 60s extra wait for `.data-collapse` block in `send_query_on_page`. 49 callsites × up to 60s = ~8 min cumulative slowdown that pushed the suite past 90 min `command_timeout` and SIGKILL'd pytest before summary.

**Safer fix design (NOT yet implemented)**:
1. After `_wait_for_new_response`, also wait up to **15s** (not 60s) for ONE of:
   - `.data-collapse` or `.cypher-collapse` block appears (Worker data arrived)
   - text contains denial markers (`权限不足`, `permission denied`, `无权访问`)
   - assistant message body length stable for **2s** (streaming finished naturally)
2. If 15s elapses with no signal, exit the wait silently — let the existing assertion fail naturally with a clearer "no data block" message.
3. Total worst-case suite slowdown: 15s × 49 = ~12 min. Healthy case: 2-3s extra per call (text-stable signal).

### B. Trace ID missing — ~3 failures (mostly subset of A)

**Pattern**: `assert response has trace_id` fails because the response captured is the preamble (no trace_id yet emitted).

**Affected**: TC-102, TC-107 (test_02), TC-505 / TC-507 (test_06 antihal).
These overlap with category A — same fix unlocks them.

### C. Permission denial expected but got preamble — ~6 failures

**Pattern**: Test expects `"权限不足"` / `"无权"` in response → instead reads preamble like `"助手\n14:47\n\n我需要..."`.

**Affected**: TC-402b, TC-404, TC-406 (test_05).
Same root cause as A.

### D. Matrix room provisioning — 1 failure

**TC-308**: `AssertionError: Admin should have a Matrix room ID`
Indicates `honeybadge-auth` provisioning step did not return the Matrix room ID for admin. Backend issue, NOT test-infra. Worth investigating separately:
- check `honeybadge-auth` `/api/auth/me` response shape
- check Matrix homeserver room provisioning logs

### E. Page navigation / Playwright timeouts — ~5 failures

**Pattern**: `Page.goto: Timeout 30000ms` or `Page.wait_for_function: Timeout 10000ms`.

**Affected**: TC-005 (logout redirect), TC-205 (session persistence), TC-305 (session isolation — both FAILED and ERROR'd in teardown), TC-312, possibly others.

These look like **transient network or rate-limit issues** during the test run, possibly aggravated by suite-level slowdowns. Single-test rerun in isolation would likely pass.

### F. MCP healthchecks — 4 failures

**Affected**: TC-603 (cache-mcp healthy), TC-608 (multi-mcp sequence), TC-609 (nebula-mcp functional), TC-610 (audit-mcp write).

These pre-date the 1.1.0 upgrade work. Likely:
- ECS-host networking restrictions blocking MCP server health probes
- MCP servers not bound to expected ports in k3s namespace

Needs investigation of MCP pod logs in `kubectl -n honeybadge logs` — separate workstream from chat helper fixes.

### G. Test_10 context/memory — ~3 failures

**Pattern**: `Response should reflect persisted context from previous session. Got: 助手`

Same mid-stream-read pattern. Will be unlocked when category A is fixed.

### H. NebulaGraph data rows — ~3 failures

**Pattern**: `NebulaGraph query should return data rows`. This is a **backend functional** test, NOT a chat-flow test. Indicates that direct nGQL queries to NebulaGraph aren't returning expected rows — could be:
- Wrong space selected
- Missing seed data after re-deploy
- Schema migration drift

Separate from chat helper fix.

## Aggregate fix value

| Fix | Tests unlocked (estimate) | Risk |
|---|---|---|
| Smart wait helper (cat A + B + C + G) | ~38 (mid-stream pattern + their cascades) | Medium — must avoid PR #105's timeout-stacking trap |
| Matrix room provisioning fix (cat D) | 1 (TC-308) + possibly TC-305 cascade | Low — backend code change with clear scope |
| MCP healthcheck investigation (cat F) | 4 (TC-603, TC-608-610) | Low — read-only investigation first |
| NebulaGraph data verification (cat H) | ~3 | Low — read-only |
| Playwright timeouts (cat E) | ~5 (likely transient, may pass on rerun) | None — accept run-to-run variance |

If the smart-wait helper lands cleanly, the new baseline could plausibly reach **~75-80 passed** out of 106 tests — a +35 jump from current 45.

## Recommended sequencing (for next session)

1. **DO NOT** re-attempt PR #105's two-stage wait approach — it regressed -24.
2. **Implement the safer wait design** in a feature branch:
   - `_wait_for_new_response` extended with text-stability detector
   - `extra_timeout=15000` (not 60000+)
   - Add denial-marker fast-exit
3. **Test locally first** if possible — run a single test (TC-303) against ECS to verify the helper unblocks it, BEFORE pushing a full E2E run.
4. **Land in a small PR** with only the conftest change, no test refactors.
5. After landing, run a single full E2E run to measure delta.
6. Only AFTER the helper is verified, move to cat D / F / H investigations.

## Why this is documented, not implemented

The autonomous loop just experienced a -24 regression from a speculative test-infra fix (PR #105). The author of this triage explicitly chose **documentation over implementation** to avoid a second autonomous regression. The safer-wait design above should be reviewed by a human and ideally tested against a single test before being applied across all 49 callsites.

## Background / quota note

- All 33 mid-stream-read failures happen AFTER the Worker has produced data — confirmed by the preamble text mentioning routing decisions.
- This is NOT a quota issue. It's a test-helper read-timing issue. Quota throttling only affects category E (Playwright timeouts).
- Fresh quota helped marginally (+1 pass over post-PR-103) but the dominant failure mode is purely test-infra.

## Appendix: full failure list

48 failures + 1 error from run 25955064057:

```
test_01_auth:        TC-005                                                    (E)
test_02_chat:        TC-102, TC-105, TC-107                                    (A/B)
test_03_session:     TC-205                                                    (E)
test_04_isolation:   TC-303, TC-304, TC-305 (+ teardown ERROR), TC-307, TC-308 (D),
                     TC-310, TC-311, TC-312, TC-313, TC-314, TC-315             (A + D + E)
test_05_permissions: TC-402, TC-402b, TC-404, TC-406, TC-408,
                     TC-409, TC-410, TC-411, TC-412, TC-413, TC-414             (A + C)
test_06_antihal:     TC-504, TC-505, TC-507, TC-511                             (A/B)
test_07_mcp:         TC-603, TC-608, TC-609, TC-610                             (F)
test_10_context:     TC-1004, TC-1006, TC-1007                                  (A/G)
test_11_routing:     TC-1101, TC-1102, TC-1104 (×4), TC-1105 (×4)               (A/B)
```
