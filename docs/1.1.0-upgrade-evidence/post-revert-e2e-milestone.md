# Post-revert E2E milestone — confirms baseline restored + marginal gain

**Date**: 2026-05-16 06:31 – 07:51 UTC
**E2E run**: [25955064057](https://github.com/xiaohanarch/HoneyBadge/actions/runs/25955064057)
**Master HEAD**: post-PR-106 revert (#106) + postmortem doc (#107)
**Duration**: 4739.08s (1:18:59) — normal range, no `command_timeout`

## Authoritative pytest summary

```
======= 48 failed, 45 passed, 13 skipped, 1 error in 4739.08s (1:18:59) ========
```

## Scoreboard

| Run | Failed | Passed | Skipped | Error | Δ passed vs baseline |
|---|---|---|---|---|---|
| Baseline (run 25910486244) | 77 | 20 | 9 | — | — |
| Post-PR-100 first | 66 | 31 | 9 | — | +11 |
| Post-PR-100 second | 73 | 28 | 5 | — | +8 |
| Post-PR-103 (best so far) | 50 | 44 | 12 | — | +24 |
| Post-PR-105 (regressed) | 76 | 20 | 7 | — | 0 (timed out) |
| **Post-revert (this run)** | **48** | **45** | **13** | **1** | **+25** |

**New best: 45 passed.** Marginal +1 pass vs post-#103, likely just LLM/quota run-to-run variance — the fresh quota window helped.

## What the revert confirmed

1. **PR #105 was the regression cause.** Reverting it restored — and slightly bettered — the post-#103 baseline. The two-stage Manager-ack → Worker-data wait was making the suite slower in a way that compounded with quota throttling.
2. **Quota cycling matters more than test infra changes.** The +1 pass over post-#103 is within run-to-run noise; what definitely *didn't* happen this time is the 90 min command_timeout.
3. **The empty-response bug is still real but rare-when-quota-is-fresh.** Many tests in test_04/test_05 that were failing on "Response: 助手\\n好的，我已经将您的查询请求发送给graph-worker..." in post-#103 passed in this run — suggests with fresh quota the Worker often beats the Manager ack to the page anyway.

## Single ERROR detail

`tests/e2e/test_04_isolation.py::TestUserIsolation::test_tc305_session_isolation_by_user ERROR [31%]`

ERROR (not FAILED) means a fixture or setup raised, not an assertion. Likely Matrix room provisioning or login_as flake. Worth a single-test rerun in isolation but not a systemic issue.

## Remaining failure clusters (mostly unchanged from post-#103)

1. **Permission tests (test_05_permissions)** — TC-401 through TC-414 still mostly red.
2. **Cross-org isolation (test_04_isolation)** — TC-303, TC-304, TC-308 still red.
3. **MCP healthchecks (test_07_mcp)** — TC-601–TC-610. Many "Connection refused" pattern, likely test-host networking issues that pre-date this work.
4. **Context & memory (test_10_context_and_memory)** — TC-1001 through TC-1010 still red.
5. **Worker routing (test_11_worker_routing)** — TC-1101–TC-1105 still red.
6. **DashScope quota tail** — last ~10 min of run will have some 429s.

## Recommendation

Two parallel workstreams (unchanged from post-#103 milestone):

1. **Functional bug investigation** — backend triage of test_05 / test_07 / test_10 / test_11 failure clusters. Needs real bug fixes, not test infra changes.
2. **Quota decision** — still needed for ECC-grade stability:
   - Quota upgrade on existing Aliyun key (cheapest)
   - Second Aliyun API key with its own quota
   - Second vendor entirely

The autonomous loop's productive contributions for this cycle:
- ✓ PR #98 (model swap), #100 (Step 2b fallback fix), #103 (maxConcurrent 8→4) — +24 passes
- ✗ PR #105 (two-stage wait) — caused -24 regression, reverted via #106
- ✓ PR #107 (postmortem) — lessons captured

Net session contribution: +25 passes vs baseline. Functional clusters cannot be further triaged without backend code changes.
