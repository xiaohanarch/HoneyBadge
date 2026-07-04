#!/usr/bin/env python3
"""Extract recent Q&A turns from the Manager ↔ user Matrix DM timeline.

Usage:
    python3 fetch-conversation-history.py --user-id admin [--max-rounds 3]

Outputs a JSON array to stdout:
    [
      {"role": "user", "content": "查询采购订单"},
      {"role": "assistant", "content": "上一轮 nGQL: MATCH ...\\n结果摘要: ..."}
    ]

Graceful degradation: on ANY error, outputs ``[]`` so the caller (fast-query.sh)
can proceed with single-turn generation — identical to today's behavior.

Design notes:
  - Reuses the DM-room resolution pattern from forward-to-user.sh:113-183
    (joined_rooms scan for 2-member rooms + newest timestamp).
  - Pairs user messages (sender @hb-{uid}:domain) with Manager replies whose
    content carries an ``x-honeybadge`` contract 002 payload (summary + cypher).
  - Truncation: keeps the last ``max_rounds`` Q&A pairs. If total chars exceed
    CHAR_BUDGET, drops to max_rounds-1 (then -1 again) until under budget.
  - Non-Q&A events (join/leave/heartbeat/notice) are filtered out.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

CHAR_BUDGET = 8000  # If history exceeds this, reduce rounds.
MANAGER_MXID = "@manager:matrix-local.hiclaw.io"


def _load_manager_token() -> tuple[str, str]:
    """Return (token, homeserver_url) from openclaw.json. Raises on missing."""
    cfg_path = os.path.expanduser("~/manager-workspace/openclaw.json")
    if not os.path.isfile(cfg_path):
        cfg_path = os.path.expanduser("~/.openclaw/openclaw.json")
    with open(cfg_path) as f:
        cfg = json.load(f)
    matrix = cfg.get("channels", {}).get("matrix", {})
    token = matrix.get("accessToken", "")
    if not token:
        raise RuntimeError("Manager Matrix accessToken not found in openclaw.json")
    # homeserver base URL; HICLAW_MATRIX_URL wins (split topology), else network alias.
    base = os.environ.get(
        "HICLAW_MATRIX_URL", "http://matrix-local.hiclaw.io:6167"
    )
    return token, base


def _api_get(base: str, token: str, path: str, timeout: float = 10.0) -> dict:
    url = f"{base}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _resolve_dm_room(base: str, token: str, user_mxid: str) -> str:
    """Find the most recently active 2-member DM room with the target user.

    Mirrors forward-to-user.sh's joined_rooms scan (more reliable than
    m.direct account data, which accumulates stale rooms from prior E2E runs).
    """
    joined = _api_get(base, token, "/_matrix/client/v3/joined_rooms").get(
        "joined_rooms", []
    )
    candidates = []
    for room_id in joined:
        try:
            members = list(
                _api_get(
                    base,
                    token,
                    f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id, safe='')}/joined_members",
                )
                .get("joined", {})
                .keys()
            )
        except Exception:
            continue
        if len(members) == 2 and user_mxid in members and MANAGER_MXID in members:
            # Newest event timestamp → most recently active room.
            try:
                data = _api_get(
                    base,
                    token,
                    f"/_matrix/client/v3/rooms/{urllib.parse.quote(room_id, safe='')}/messages?dir=b&limit=1",
                )
                events = data.get("chunk", [])
                ts = events[0].get("origin_server_ts", 0) if events else 0
            except Exception:
                ts = 0
            candidates.append((ts, room_id))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _extract_qa_pairs(events: list[dict], user_mxid: str) -> list[dict[str, str]]:
    """Pair user questions with Manager replies carrying x-honeybadge payloads.

    events: Matrix events in chronological order (oldest first).
    Returns a list of {"role","content"} dicts, newest last.
    """
    # Filter to relevant message events, preserving chronological order.
    # Matrix /messages?dir=b returns newest-first; caller should reverse.
    relevant: list[dict] = []
    for ev in events:
        etype = ev.get("type", "")
        if etype != "m.room.message":
            continue
        content = ev.get("content", {}) or {}
        if content.get("msgtype") != "m.text":
            continue
        sender = ev.get("sender", "")
        if sender == user_mxid:
            # User question
            body = content.get("body", "")
            if not body or not body.strip():
                continue
            relevant.append({"role": "user", "content": body, "_sender": sender})
        elif sender == MANAGER_MXID:
            # Manager reply — only count it as an answer if it carries a
            # contract 002 x-honeybadge payload (structured Q&A result).
            xhb = content.get("x-honeybadge")
            if not isinstance(xhb, dict):
                continue
            payload = xhb.get("payload") or {}
            summary = payload.get("summary", "")
            cypher = payload.get("cypher", "")
            if not summary and not cypher:
                continue
            assistant_text = f"上一轮 nGQL: {cypher}\n结果摘要: {summary}"
            relevant.append({"role": "assistant", "content": assistant_text, "_sender": sender})

    # Pair consecutive user→assistant messages into Q&A turns.
    pairs: list[dict[str, str]] = []
    i = 0
    while i < len(relevant):
        msg = relevant[i]
        if msg["role"] == "user":
            # Find the next assistant reply (skip stray consecutive user msgs).
            assistant = None
            j = i + 1
            while j < len(relevant):
                if relevant[j]["role"] == "assistant":
                    assistant = relevant[j]
                    break
                j += 1
            if assistant:
                pairs.append({"role": "user", "content": msg["content"]})
                pairs.append({"role": "assistant", "content": assistant["content"]})
                i = j + 1
            else:
                i += 1
        else:
            i += 1
    return pairs


def _truncate(pairs: list[dict[str, str]], max_rounds: int) -> list[dict[str, str]]:
    """Keep the last ``max_rounds`` Q&A pairs; shrink if over CHAR_BUDGET."""
    rounds = max_rounds
    while rounds > 0:
        keep = pairs[-(rounds * 2):]  # last N pairs (2 messages each)
        total = sum(len(m["content"]) for m in keep)
        if total <= CHAR_BUDGET:
            return keep
        rounds -= 1  # too big, drop oldest round and retry
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, help="HoneyBadge user id (e.g. admin)")
    parser.add_argument("--max-rounds", type=int, default=3, help="Q&A pairs to retain")
    args = parser.parse_args()

    try:
        token, base = _load_manager_token()
        matrix_domain = os.environ.get(
            "HICLAW_MATRIX_DOMAIN", "matrix-local.hiclaw.io"
        )
        # Strip hb- prefix to avoid @hb-hb-admin:...
        uid_clean = args.user_id.removeprefix("hb-")
        user_mxid = f"@hb-{uid_clean}:{matrix_domain}"

        room_id = _resolve_dm_room(base, token, user_mxid)
        if not room_id:
            print("[]")
            return 0

        # Fetch more events than needed so we can filter out non-Q&A noise
        # (join/leave/heartbeat). max_rounds*4 gives headroom.
        limit = max(args.max_rounds * 4, 12)
        encoded_room = urllib.parse.quote(room_id, safe="")
        data = _api_get(
            base,
            token,
            f"/_matrix/client/v3/rooms/{encoded_room}/messages?dir=b&limit={limit}",
        )
        events = data.get("chunk", [])
        # dir=b → newest first; reverse for chronological order.
        events.reverse()

        pairs = _extract_qa_pairs(events, user_mxid)
        pairs = _truncate(pairs, args.max_rounds)
        print(json.dumps(pairs, ensure_ascii=False))
        return 0
    except Exception as e:
        # Graceful degradation: any error → empty history, query proceeds single-turn.
        sys.stderr.write(f"fetch-conversation-history: {e}\n")
        print("[]")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
