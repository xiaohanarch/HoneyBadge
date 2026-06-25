#!/usr/bin/env python3
"""Watch for new 2-member rooms and set is_direct=true on Manager's member state.

This is a workaround for OpenClaw v1.1.2's direct-room detection: the gateway
checks the CURRENT m.room.member state (which is the join event), but Matrix
only sets is_direct on the invite event. When the Manager joins, the join event
overwrites the invite event and is_direct is lost.

This script polls joined rooms every 2 seconds and patches any 2-member room
that is missing is_direct=true on the Manager's member state.
"""
import json, urllib.request, urllib.parse, time, sys, os

CONFIG_PATH = os.path.expanduser(
    os.environ.get("OPENCLAW_CONFIG", "/root/manager-workspace/.openclaw/openclaw.json")
)
MANAGER_ID = "@manager:matrix-local.hiclaw.io"
BASE = os.environ.get("HICLAW_MATRIX_URL", "http://matrix-local.hiclaw.io:6167")
POLL_INTERVAL = 2  # seconds

def load_token():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    return cfg["channels"]["matrix"]["accessToken"]

def api(method, path, token, data=None):
    url = BASE + path
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def fix_rooms(token):
    joined = api("GET", "/_matrix/client/v3/joined_rooms", token).get("joined_rooms", [])
    fixed = 0
    for room_id in joined:
        try:
            enc_room = urllib.parse.quote(room_id, safe="")
            members_data = api("GET", "/_matrix/client/v3/rooms/" + enc_room + "/joined_members", token)
            members = list(members_data.get("joined", {}).keys())
            if len(members) != 2 or MANAGER_ID not in members:
                continue
            enc_mgr = urllib.parse.quote(MANAGER_ID, safe="")
            try:
                state = api("GET", "/_matrix/client/v3/rooms/" + enc_room + "/state/m.room.member/" + enc_mgr, token)
            except Exception:
                continue
            if state.get("is_direct") is True:
                continue
            displayname = state.get("displayname", "manager")
            api("PUT", "/_matrix/client/v3/rooms/" + enc_room + "/state/m.room.member/" + enc_mgr, token,
                {"membership": "join", "displayname": displayname, "is_direct": True})
            fixed += 1
        except Exception:
            pass
    return fixed

def main():
    token = load_token()
    print(f"[fix-direct-rooms] started, polling every {POLL_INTERVAL}s", flush=True)
    while True:
        try:
            fixed = fix_rooms(token)
            if fixed > 0:
                print(f"[fix-direct-rooms] fixed {fixed} rooms", flush=True)
        except Exception as e:
            print(f"[fix-direct-rooms] error: {e}", flush=True)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
