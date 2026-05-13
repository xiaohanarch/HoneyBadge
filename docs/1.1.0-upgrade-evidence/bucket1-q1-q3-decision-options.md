# Bucket 1 Q1–Q3 — memorySearch product decision options

> Branch: `ralph/memorysearch-decision`
> Date: 2026-05-13
> Status: **Decision recorded 2026-05-13 — Bundle A.** See decision block at the bottom of this file. Q4 was closed earlier (see `bucket1-memorysearch-default-check.log`).
> Source of questions: `docs/1.1.0-upgrade-followups.md` §Bucket 1 + `docs/1.1.0-upgrade-suggestion.md` §六.

This doc lays out the three open product questions, the trade-offs, and a concrete recommendation per question so a single review pass can resolve all three. After you pick, this doc becomes the implementation contract for the follow-up commits on this branch.

---

## Context recap

The Manager agent has a built-in `memorySearch` extension that, when enabled, embeds local memory files (`MEMORY.md`, `memory/YYYY-MM-DD.md`) and exposes a `memory_search` tool to the LLM. Today we have it **fully disabled** because:

1. HoneyBadge's 5-layer anti-hallucination framework requires every ERP business answer to flow through Worker → MCP → NebulaGraph → audit log (L4 raw passthrough + L5 full-chain audit). A vector-recall shortcut bypasses both layers.
2. `SOUL.md:32` bans `memory_search` for ERP data: *"Never use tools like `exec`, `memory_search`, or `read_file` to try to find ERP data directly."*
3. Our Higress AI gateway only routes `/v1/chat/completions`, not `/v1/embeddings`, so even if we wanted memorySearch enabled it would crash on the first index build.
4. Manager workspace has no `MEMORY.md`/`memory/*.md` files anyway, so the index would be empty.

After Q4's evidence: in v1.1.0 the disable path is `HICLAW_EMBEDDING_MODEL=""` in compose. That single env knob controls everything below.

---

## Q1. SOUL.md ban granularity

**Status quo** (`hiclaw/manager/agent/SOUL.md:32`):

> *"Never use tools like `exec`, `memory_search`, or `read_file` to try to find ERP data directly."*

This already scopes to "ERP data" — it does **not** ban operational memory (user preferences, dispatch heuristics, conversation context).

### Options

| # | Option | SOUL change | What memory can do |
|---|---|---|---|
| **1a** | **Status quo, keep wording** | none | Nothing — memorySearch runtime is also disabled, so the ban is theoretical |
| **1b** | **Explicit dual-scope wording** | Rewrite line 32 to spell out "ERP business data: forbidden; operational signals: allowed" | Same effect as 1a today, but the wording survives if/when memorySearch is later enabled |
| **1c** | **Drop the ban entirely** | Remove line 32 | Manager free to use `memory_search` for anything — **violates L4/L5 anti-hallucination layers** |

### Trade-offs

- 1a is free; the wording is already scoped to ERP. Risk: a future engineer reading SOUL.md doesn't realize "ERP data" was intended to be a narrow scope, over-applies the ban, and blocks future operational-memory work.
- 1b costs one short edit and makes the intent unambiguous. The new wording proposed in `docs/1.1.0-upgrade-suggestion.md` §六 Q1 is good:
  > *"Never use `memory_search` to retrieve ERP business data (suppliers, orders, invoices, amounts, transactions). It MAY be used to recall operational preferences, routing heuristics, or conversation context signals."*
- 1c is rejected upstream — `docs/1.1.0-upgrade-suggestion.md` flags it as "not recommended" because it directly contradicts the L4 raw-passthrough rule.

### Recommendation

**1b — Explicit dual-scope wording.** Costs nothing today, future-proofs the SOUL contract for whichever direction Q2/Q3 land in.

### What changes if you pick 1b

- `hiclaw/manager/agent/SOUL.md:32` — edit one line.
- `init-workers.sh` re-syncs SOUL to MinIO automatically; no infra change.

---

## Q2. Higress `/v1/embeddings` upstream choice

**Status quo:** no `/v1/embeddings` route exists on the AI gateway. `HICLAW_EMBEDDING_MODEL=""` suppresses memorySearch entirely.

This question is only live if you want operational memory — i.e. you pick anything other than 1a/1b "do nothing" for Q1+Q3.

### Options

| # | Provider | Endpoint | Model | API key | Pros | Cons |
|---|---|---|---|---|---|---|
| **2a** | **Keep disabled** | n/a | n/a | n/a | No infra change, no new failure surface | No operational memory — Manager has no long-term recall |
| **2b** | DashScope embeddings | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `text-embedding-v4` | Reuse existing DashScope key (`LLM_API_KEY`) or a separate `EMBEDDING_API_KEY` | Same vendor as chat upstream → one billing relationship; v4 is current production-grade | Different baseUrl from coding endpoint — needs second Higress route + consumer; quota shared with chat usage |
| **2c** | MiniMax embeddings | `https://api.minimaxi.com/v1` | `embo-01` | New MiniMax key | Second vendor for resilience | We migrated away from MiniMax in PR #60 due to quota cap; re-introducing it adds an extra credential to rotate |
| **2d** | Self-hosted Ollama | `http://ollama.honeybadge.svc.cluster.local/v1` | `bge-m3` (multilingual) or `mxbai-embed-large` | None | Zero per-token cost, no external dependency, no PII leaving the cluster | Adds an Ollama Deployment + GPU/CPU footprint; embedding latency dependent on cluster sizing |

### Trade-offs

- **2a** is the right answer if Q1+Q3 land on "no operational memory needed". Defer this whole question until that need is real.
- **2b** is the cheapest path *if* memory is wanted. The pattern mirrors Layer A of the existing setup — one env var (`HICLAW_EMBEDDING_MODEL=text-embedding-v4`) plus one Higress consumer route entry. ~1 hour of work.
- **2c** is the worst of both worlds — vendor diversity but with a vendor we just left due to limits.
- **2d** is the right long-term answer if/when this codebase ships to airgapped enterprise customers (PHI/ERP data leaving the cluster is a compliance concern). Higher up-front cost.

### Recommendation

**2a (keep disabled) for now.** Combined with Q3 below: there's no clear product need for operational memory today; Manager's session-scoped context is sufficient for the dispatch/coordination role. Re-open Q2 when one of these is true:

- Manager is observed repeatedly re-deriving the same routing heuristics across sessions, *and* that latency is user-visible.
- A user-preference UX feature ("remember I prefer Chinese tabular output") gets prioritized.
- Compliance review forces a content-isolated embedding path (then jump directly to 2d).

### What changes if you pick 2a

Nothing. Keep the current `HICLAW_EMBEDDING_MODEL=` empty string. No Higress route added.

### What changes if you pick 2b instead

- `deploy/docker/.env.example` and `.env` — add `EMBEDDING_API_KEY` (or document key reuse).
- `deploy/docker/docker-compose.yaml` — set `HICLAW_EMBEDDING_MODEL=text-embedding-v4`.
- `deploy/hiclaw/init-workers.sh` (or its v1.1.0 equivalent) — add a second Higress AI route for `/v1/embeddings` pointing at `dashscope.aliyuncs.com/compatible-mode/v1`.
- `deploy/hiclaw/aigw-bypass.conf.template` — add a parallel `location /v1/embeddings` block forwarding to the embeddings upstream (currently only `/v1/*` to coding endpoint, which lacks embeddings).
- `deploy/k8s/secrets.yaml` and the eventual K8s Higress CR — mirror the same.
- Smoke test: `curl -s -H "Authorization: Bearer …" http://aigw-local.hiclaw.io:8080/v1/embeddings -d '{"model":"text-embedding-v4","input":"hello"}'` → expect 200 + vector.

---

## Q3. Memory file write strategy

Only live if Q2 ≠ 2a.

### Sub-questions

#### Q3a. Who writes memory files?

| # | Option | Mechanism | Pros | Cons |
|---|---|---|---|---|
| **3a-i** | **Manager autonomous (`memoryFlush`)** | openclaw's built-in compaction trigger: when a session approaches the context-window threshold, openclaw injects a system prompt telling the Manager to write a memory note before compaction | Native to openclaw, zero extra plumbing | Manager decides what to remember — quality depends on prompt engineering; **bypasses L5 if not audited** |
| **3a-ii** | **Operator-driven offline** | Periodic script reads conversation logs out of the audit DB, distils them with an LLM call, writes `memory/YYYY-MM-DD.md` to MinIO | Full audit trail; operator can sanitize PII | New offline pipeline to build and operate |
| **3a-iii** | **Hybrid** | 3a-i for ephemeral session notes, 3a-ii for persisted-to-disk + auditable summaries | Best of both | Most complex |

#### Q3b. What gets written?

- Operational preferences ("user X prefers Chinese tabular output").
- Routing heuristics ("dispatch rule R triggered 12× in the last 30 days on supplier-balance queries").
- **Never:** raw ERP rows, supplier names with amounts, invoice numbers — those are L4/L5-protected.

#### Q3c. Does memory file change feed L5 audit log?

| # | Option | What it means |
|---|---|---|
| **3c-i** | **No** | memory diffs only live in MinIO; not in PostgreSQL audit | **Creates an L5 blindspot**: an attacker who poisons memory files can influence Manager output without trace |
| **3c-ii** | **Yes (recommended)** | Every memory file write triggers an entry in `audit_log` (via `audit-mcp`) with: who/what/diff hash/timestamp | Preserves L5 invariant: every input to a Manager answer is traceable |

### Trade-offs

- 3a-i + 3c-i is what openclaw gives you out-of-the-box. It is **incompatible** with the project's L4/L5 invariants as written in CLAUDE.md.
- 3a-i + 3c-ii is the minimum bar to make autonomous memory safe. Requires a small audit-mcp hook (`POST /audit/memory-event`) and a tiny shim in either `manager-init-internal.sh` or a Higress filter to intercept memory writes.
- 3a-ii + 3c-ii is the most defensible posture and is the natural extension of the existing nightly L5 audit pipeline.

### Recommendation

**Defer Q3 entirely until Q2 changes.** If/when Q2 lands on 2b/2d:

- 3a-ii + 3c-ii. Operator-driven memory write, every diff audited.
- Rationale: HoneyBadge's value prop is "trustworthy answers backed by a tamper-evident chain". Autonomous memory writes without audit hooks would directly contradict that.

### What changes if you pick 3a-ii + 3c-ii

- `src/honeybadge/server/` — new `memory_writer` module that pulls conversation summaries from `audit_log` and writes deduped memory entries.
- `mcp-servers/honeybadge-audit-mcp/` — extend `audit_log` schema with `memory_event` rows.
- `deploy/docker/docker-compose.yaml` — add a cron-style sidecar (or k8s CronJob) that runs the memory_writer nightly.
- `hiclaw/manager/agent/SOUL.md` — add an explicit clause: *"Memory files (`MEMORY.md`, `memory/*.md`) are read-only at runtime. Memory writes happen via the offline operator pipeline; do not attempt to write memory files yourself."*

---

## Combined recommendation

| Q | Pick | Cost | Touches |
|---|---|---|---|
| **Q1** | **1b** Explicit dual-scope SOUL wording | 1 line edit | `hiclaw/manager/agent/SOUL.md:32` |
| **Q2** | **2a** Keep disabled | 0 | none |
| **Q3** | n/a — gated on Q2 ≠ 2a | 0 | none |

Net effect: one SOUL line edit, no infra change. Memory remains disabled, but the contract is now precise enough that a future re-enable is unblocked from a documentation standpoint.

If you instead want to unlock operational memory now, the cheapest viable bundle is **1b + 2b + 3a-ii/3c-ii**, sized at roughly:

- ~30 min: SOUL edit + smoke-test embedding route via DashScope.
- ~2 hours: nginx-bypass + Higress route + env example update.
- ~half day: audit-mcp `memory_event` schema + memory_writer module + nightly cron.

---

## Decision capture

After you pick, I'll:

1. Write your choices into this file's `Decision: <date>` block below.
2. Update `docs/1.1.0-upgrade-followups.md` Bucket 1 with the chosen path.
3. Open follow-up commits / PR(s) implementing the picks.

```
Decision date: 2026-05-13
Bundle:        A — Status quo + SOUL clarification
Q1:            1b   Explicit dual-scope SOUL wording (ERP business data forbidden; operational signals allowed)
Q2:            2a   Keep disabled
Q3a:           n/a  (gated on Q2 ≠ 2a)
Q3b:           n/a
Q3c:           n/a
Notes:         No infra change. Memory remains disabled. Contract is now precise enough
               that a future re-enable is unblocked from the documentation standpoint —
               only Q2 (embedding upstream) and Q3 (write strategy) need fresh decisions
               if/when a real product driver appears for operational memory.

               Implementation:
                 hiclaw/manager/agent/SOUL.md:32 — one-line edit, scoping
                 the ban to ERP business facts and explicitly carving out
                 operational-signal recall as future-allowed.
                 init-workers.sh re-syncs SOUL to MinIO automatically on
                 the next compose up / restart of the workers init job.

               Re-open trigger conditions for Q2/Q3 (paste here when any becomes true):
                 - Manager observed repeatedly re-deriving the same routing
                   heuristics across sessions, latency user-visible.
                 - A user-preference UX feature ("remember I prefer Chinese
                   tabular output") gets prioritized in the roadmap.
                 - Compliance review forces a content-isolated embedding
                   path (then jump straight to Bundle C / Option 2d).
```
