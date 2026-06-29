#!/usr/bin/env bash
# route-and-execute.sh — Unified router + executor for ERP queries
#
# Eliminates the LLM's non-deterministic routing decision by combining
# router.sh + fast-query.sh into a single Bash tool call. The LLM only
# needs to call this ONE script; it never needs to decide which path to take.
#
# Usage:
#   bash route-and-execute.sh --question "..." --user-id "admin"
#
# Behavior:
#   1. Runs router.sh to determine the route (fast-query | graph-worker | analytics-worker)
#   2. If "fast-query": executes fast-query.sh (with --forward-to-user-id) and exits.
#      The LLM does NOT need to do anything else — the result is sent to the user.
#   3. If "graph-worker" or "analytics-worker": prints "ROUTE=<worker>" so the LLM
#      knows to use dispatch.sh.
#
# Exit codes (same as fast-query.sh for the fast-query path):
#   0 — success (fast-query sent contract 002 to user, OR route is graph/analytics worker)
#   1 — parameter error
#   2 — nGQL generation failed
#   3 — query execution failed
#   4 — L3_PERMISSION denied (error already forwarded to user)

set -euo pipefail

QUESTION=""
USER_ID=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --question)  QUESTION="$2"; shift 2 ;;
    --user-id)   USER_ID="$2";  shift 2 ;;
    *) shift ;;
  esac
done

[[ -z "$QUESTION" ]] && { echo '{"error":"--question is required"}'; exit 1; }
[[ -z "$USER_ID" ]]  && { echo '{"error":"--user-id is required"}';  exit 1; }

# Persist user_id so dispatch-to-worker.sh can recover it.
# The Manager LLM calls route-and-execute.sh and dispatch.sh as separate
# bash tool invocations — USER_ID doesn't carry over. When the LLM
# forgets to re-extract USER_ID for dispatch.sh, it defaults to "manager"
# (its own identity), causing L3 to use org_ids=[1] → 0 results.
# dispatch.sh reads this file when --user-id is "manager" or empty.
echo "$USER_ID" > /tmp/.last-route-user-id

# Step 1: Route
ROUTE=$(bash /opt/honeybadge/config/manager/agent/skills/fast-query/router.sh "$QUESTION")

# Step 2: Execute based on route
case "$ROUTE" in
    fast-query)
        # Execute fast-query.sh directly — handles nGQL generation, execution,
        # L3 permission enforcement, and contract 002 forwarding.
        exec bash /opt/honeybadge/config/manager/agent/skills/fast-query/fast-query.sh \
            --question "$QUESTION" \
            --user-id "$USER_ID" \
            --task-id "fast-$(date +%s%3N)" \
            --forward-to-user-id "$USER_ID"
        ;;
    *)
        # Output the route so the LLM can use dispatch.sh
        echo "ROUTE=$ROUTE"
        exit 0
        ;;
esac
