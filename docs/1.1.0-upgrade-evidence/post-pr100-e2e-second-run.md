# Post-PR-100 E2E rerun after quota window reset (Option D verification)

**Date**: 2026-05-15 19:50 – 21:13 UTC
**E2E run**: [25938194180](https://github.com/xiaohanarch/henoneybadge/actions/runs/25938194180)
**Wait between runs**: 65 minutes (first run ended 18:38 UTC, second triggered 19:50 UTC)

## Result

`============ 73 failed, 28 passed, 5 skipped in 4930.69s (1:22:10) =============`

| Run | Failed | Passed | Skipped | Δ passed vs baseline |
|---|---|---|---|---|
| Baseline (run 25910486244) | 77 | 20 | 9 | — |
| First post-PR-100 run (25931384765) | 66 | 31 | 9 | +11 |
| Second post-PR-100 run (25938194180) | **73** | **28** | **5** | +8 |

The wait-and-retry strategy (Option D) **does not work**. Pass count even regressed slightly (31 → 28), well below 80-test target.

## Why Option D failed

DashScope's hourly quota is exhausted within the E2E run itself, not just lingering from the previous run:

1. The E2E suite issues ~97 chat tests, each averaging 1–4 LLM calls
2. Each call sends 7K–28K-token context windows to qwen3-coder-plus
3. Aggregate token usage exceeds the API key's hourly allocation partway through the run
4. Subsequent requests all get `429 hour allocated quota exceeded`
5. Worker logs `failoverReason=rate_limit fallbackConfigured=false decision=surface_error`
6. Frontend never receives a trace_id; Playwright `Page.wait_for_function` times out at 20s

## Why naive Option A won't work either

The openclaw `agents.defaults.model.fallbacks: ["provider/model"]` array (schema verified against openclaw upstream docs) requires that the fallback resolves to a **provider with a separate quota pool**.

Our current Higress configuration has a single `openai-compat` upstream pointing at `coding.dashscope.aliyuncs.com` with one Aliyun Bailian API key. All model SKUs on that endpoint (qwen3-coder-plus, qwen3-coder-flash) share the same per-API-key quota. Adding a fallback like `hiclaw-gateway/qwen3-coder-flash` would route to the same upstream key and trigger the same 429.

To make Option A effective, we need one of:

1. **Second Aliyun API key** with its own quota — add a `qwen-plus` provider to Higress + add `fallbacks: ["qwen-plus/qwen3-coder-flash"]` in worker openclaw.json
2. **Different vendor entirely** as fallback (e.g. moonshot, deepseek, glm) — requires McpBridge service-source + LLM route per provider
3. **Quota upgrade** on the existing API key (purely a billing action; no code change)

All three require credentials or billing decisions that are out of scope for the autonomous loop.

## Adjacent verified findings

- PR #98 (model swap) + PR #100 (Step 2b primary fallback fix) are **both correctly deployed** and **functioning**. Confirmed by diagnose run 25931291486: workers report `primary: hiclaw-gateway/qwen3-coder-plus`, gateway shows `agent model: hiclaw-gateway/qwen3-coder-plus`, embedded runs log `provider=hiclaw-gateway model=qwen3-coder-plus`.
- Context overflow regressions are gone — no `Context overflow` events post-deploy.
- `Redis on localhost:6379 connection refused` (test_tc603_cache_mcp_healthy) is an unrelated test-runner-local issue, predates this work.

## Recommended user actions

Order of preference:

1. **Quota upgrade** on the Aliyun Bailian API key (cheapest, no code)
2. Provision a **second API key** (Aliyun or other vendor) and wire it into Higress + Step 2b adds `fallbacks` array
3. Reduce E2E concurrency (slowest but free) — set `pytest -n 1` and add per-test backoff

The autonomous loop has done all the verification it can without a credential decision. Surfacing to user.
