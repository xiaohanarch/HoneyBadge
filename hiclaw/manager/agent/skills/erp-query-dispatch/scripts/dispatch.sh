#!/bin/bash
# dispatch.sh — HiClaw skill entry point for erp-query-dispatch
#
# HiClaw's skill execution system looks for dispatch.sh as the entry point
# for skill invocation. This wrapper delegates to dispatch-to-worker.sh.
#
# Usage (via HiClaw skill or direct exec):
#   bash dispatch.sh --worker graph-worker --task-id task-... --message "..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/dispatch-to-worker.sh" "$@"
