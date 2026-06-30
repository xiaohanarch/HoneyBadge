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

# Recover real user_id when the LLM defaults to "manager".
# The Manager LLM sometimes forgets to re-extract USER_ID from the
# Matrix sender metadata, passing "manager" (its own identity) instead.
# This causes L3 to use org_ids=[1] (default restrictive permissions)
# instead of the user's actual permissions.
# Same recovery pattern as dispatch-to-worker.sh lines 42-61.
if [[ "$USER_ID" == "manager" ]]; then
    if [[ -f /tmp/.last-route-user-id ]]; then
        RECOVERED_ID=$(cat /tmp/.last-route-user-id 2>/dev/null || true)
        if [[ -n "$RECOVERED_ID" && "$RECOVERED_ID" != "manager" ]]; then
            echo "RECOVERED_USER_ID=$RECOVERED_ID (was 'manager', recovered from previous route-and-execute.sh)" >&2
            USER_ID="$RECOVERED_ID"
        fi
    fi
fi

# Persist user_id so dispatch-to-worker.sh can recover it.
# Don't overwrite with "manager" — preserves the last good value for
# subsequent calls in the same session.
if [[ "$USER_ID" != "manager" ]]; then
    echo "$USER_ID" > /tmp/.last-route-user-id
fi

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
