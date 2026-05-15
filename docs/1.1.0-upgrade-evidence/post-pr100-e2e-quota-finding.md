# Post-PR-100 E2E run: DashScope hourly quota exhaustion

**Date**: 2026-05-15 17:19 – 18:38 UTC
**E2E run**: [25931384765](https://github.com/xiaohanarch/HoneyBadge/actions/runs/25931384765)
**Diagnose**: [25935035844](https://github.com/xiaohanarch/HoneyBadge/actions/runs/25935035844) (right after E2E)

## Summary

- Baseline (pre-fix, run 25910486244): **77 failed / 20 passed / 9 skipped**
- After PR #98 (glm-5 → qwen3-coder-plus) + PR #100 (Step 2b primary fallback fix): **66 failed / 31 passed / 9 skipped**
- Net improvement: **+11 passing tests**
- Remaining failures: all caused by one new root cause — DashScope `429 hour allocated quota exceeded`

## Root cause of remaining 66 failures

Workers' openclaw daily log shows the chat pipeline now reaches the upstream LLM successfully (no more context overflow), but the upstream returns 429:

```
[agent/embedded] embedded run agent end:
  runId=2f03c663-... isError=true
  model=qwen3-coder-plus provider=hiclaw-gateway
  error=⚠️ hour allocated quota exceeded.
  rawError=429 hour allocated quota exceeded.

[agent/embedded] embedded run failover decision:
  stage=assistant decision=surface_error
  reason=rate_limit
  fallbackConfigured=false
  providerRuntimeFailureKind=rate_limit
```

The openclaw runtime detected the 429 as a `rate_limit` failure, looked for a configured fallback model, found none (`fallbackConfigured=false`), and surfaced the error to the user. The frontend then sees no trace_id and no data table, causing the Playwright `Page.wait_for_function` to time out after 20s. This cascades into the bulk of the 66 failures.

## Why this is not a code defect in our repo

1. PR #100 patches Step 2b in `deploy/hiclaw/manager-init-internal.sh` so worker openclaw.json primary is reliably set to `hiclaw-gateway/qwen3-coder-plus`. Verified by diagnose run 25931291486 — both workers now log `agent model: hiclaw-gateway/qwen3-coder-plus` and `provider=hiclaw-gateway model=qwen3-coder-plus`.
2. The 429 is returned by Aliyun DashScope (`coding.dashscope.aliyuncs.com`), not by Higress, not by openclaw, not by our code.
3. The E2E suite issues ~97 tests, each making 1–4 LLM calls, often with 7K–28K-token context windows. Sustained load against the qwen3-coder-plus tier's hourly quota exhausts it partway through the run.

## Options (need user decision)

### A. Configure openclaw `agents.defaults.model.fallback` in Step 2b
- Pros: Surgical, keeps qwen3-coder-plus for happy-path long-context queries; failover to a model with a separate quota pool (e.g. `qwen-plus`, `qwen-turbo`) when 429 fires.
- Risks: Openclaw fallback schema not documented in this repo; field name might differ (`fallback`, `fallbacks[]`, `profiles[].onFailure`, etc). Wrong field name is silently ignored.
- Action: Verify schema against openclaw upstream before patching.

### B. Upgrade DashScope quota
- Pros: Cleanest, no code change.
- Cons: External billing decision.

### C. Throttle E2E concurrency / add per-test backoff
- Pros: No production change.
- Cons: E2E run wall-time grows; doesn't fix the issue for real users under load.

### D. Wait for quota window to reset and re-run E2E (zero-cost verification)
- Aliyun quota resets hourly. Re-running E2E ~60–90 min after the previous run will indicate whether the model swap alone (without fallback) is sufficient for a single non-stressed run.
- This is the cheapest next step before committing to any of A/B/C.

## Adjacent issues surfaced (lower priority)

- `test_tc603_cache_mcp_healthy`: `Redis on localhost:6379 connection refused` — looks like a test-runner-local check rather than in-cluster Redis. Pre-existing.
- `Matrix M_NOT_FOUND TURN URIs (404)` from `[CON] error` — no TURN server configured; non-blocking for chat.
- `model-pricing pricing bootstrap failed: TypeError: fetch failed` — openclaw worker can't reach pricing endpoint at startup; benign warning.

## Verification artifacts

- v13 diagnose run 25931291486 (post-PR-100, pre-E2E): primary=qwen3-coder-plus on both workers, all `models[].id` entries are qwen3-coder-plus, manager `HICLAW_DEFAULT_MODEL=qwen3-coder-plus`, server `LLM_MODEL=qwen3-coder-plus`.
- v13 diagnose run 25935035844 (post-E2E): same primary, log shows 429s correlated with E2E test timestamps.

## Recommended next action

1. Wait ≥60 min for DashScope hourly quota to reset.
2. Re-trigger `E2E Tests on ECS` workflow.
3. If pass count climbs significantly (target: >80), the model swap alone is sufficient. Remaining tail-end failures (still <20) can then be triaged individually.
4. If pass count stalls at 30–40, implement Option A (openclaw fallback) — but verify schema against openclaw upstream first.
