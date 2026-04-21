#!/usr/bin/env python3
"""
HoneyBadge NebulaGraph Test Data Loader v2.0

Loads vertex and edge CSV files into NebulaGraph honeybadge space.
Schema types are fetched dynamically via DESCRIBE TAG/EDGE.

Usage:
  # Start port-forward first:
  kubectl port-forward svc/nebula-graphd 9669:9669 -n honeybadge &
  # Then run:
  python3 load_nebula.py
"""
import csv
import json
import sys
import datetime
from pathlib import Path

from nebula3.gclient.net import ConnectionPool
from nebula3.Config import Config

# ─── Config ────────────────────────────────────────────────────────────────
NEBULA_HOST    = "localhost"
NEBULA_PORT    = 9669
NEBULA_USER    = "root"
NEBULA_PASSWORD = "nebula"
NEBULA_SPACE   = "honeybadge"

DATA_DIR    = Path("/opt/honeybadge/deploy/test-data/csv")
VERTEX_DIR  = DATA_DIR / "vertices"
EDGE_DIR    = DATA_DIR / "edges"

BATCH_SIZE  = 200   # rows per INSERT statement
# ───────────────────────────────────────────────────────────────────────────


def _str_val(b) -> str:
    """Decode bytes or return str from a nebula Value"""
    if isinstance(b, bytes):
        return b.decode("utf-8")
    return str(b)


def describe_tag(session, name: str) -> dict[str, str]:
    """Return {prop_name: type_str} for a tag, preserving column order."""
    r = session.execute(f"DESCRIBE TAG `{name}`")
    if not r.is_succeeded():
        return {}
    props = {}
    for row in r.rows():
        field = _str_val(row.values[0].get_sVal())
        ptype = _str_val(row.values[1].get_sVal())
        props[field] = ptype
    return props


def describe_edge(session, name: str) -> dict[str, str]:
    """Return {prop_name: type_str} for an edge type."""
    r = session.execute(f"DESCRIBE EDGE `{name}`")
    if not r.is_succeeded():
        return {}
    props = {}
    for row in r.rows():
        field = _str_val(row.values[0].get_sVal())
        ptype = _str_val(row.values[1].get_sVal())
        props[field] = ptype
    return props


def _iso_to_ts(s: str) -> int | None:
    """Parse ISO 8601 datetime string → Unix timestamp (seconds)."""
    if not s:
        return None
    s = s.strip()
    # Handle trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        pass
    # Fallback: try plain int
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def fmt(raw, ptype: str) -> str:
    """Format a raw JSON string value into the correct nGQL literal."""
    pt = ptype.upper().strip()

    # Null / missing
    if raw is None or raw == "" or str(raw).lower() in ("none", "null"):
        return "null"

    v = str(raw)

    if "INT" in pt:
        try:
            return str(int(float(v)))
        except (ValueError, TypeError):
            return "null"

    if "DOUBLE" in pt or "FLOAT" in pt:
        try:
            return str(float(v))
        except (ValueError, TypeError):
            return "null"

    if "BOOL" in pt:
        return "true" if v.lower() in ("true", "1", "yes") else "false"

    if "TIMESTAMP" in pt:
        ts = _iso_to_ts(v)
        return str(ts) if ts is not None else "0"

    # STRING — escape backslash then double-quote
    escaped = v.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def exec_batch(session, ngql: str, label: str):
    r = session.execute(ngql)
    if not r.is_succeeded():
        print(f"\n    [ERROR] {label}: {r.error_msg()[:200]}")


# ─── Vertex loader ─────────────────────────────────────────────────────────

def load_vertices(session, csv_path: Path) -> int:
    tag = csv_path.stem
    schema = describe_tag(session, tag)
    if not schema:
        print(f"  SKIP {tag}: no schema found")
        return 0

    cols     = list(schema.keys())
    col_list = ", ".join(f"`{c}`" for c in cols)
    total    = 0
    batch: list[str] = []

    def flush():
        nonlocal total
        if not batch:
            return
        vals = ",\n  ".join(batch)
        ngql = f"INSERT VERTEX IF NOT EXISTS `{tag}`({col_list}) VALUES\n  {vals};"
        exec_batch(session, ngql, tag)
        total += len(batch)
        batch.clear()

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            if len(row) < 2:
                continue
            vid = row[0]
            try:
                props: dict = json.loads(row[1])
            except (json.JSONDecodeError, IndexError):
                continue

            vals = [fmt(props.get(c), schema[c]) for c in cols]
            vid_e = vid.replace("\\", "\\\\").replace('"', '\\"')
            batch.append(f'"{vid_e}":({", ".join(vals)})')

            if len(batch) >= BATCH_SIZE:
                flush()

    flush()
    return total


# ─── Edge loader ───────────────────────────────────────────────────────────

def load_edges(session, csv_path: Path) -> int:
    etype  = csv_path.stem
    schema = describe_edge(session, etype)
    # schema may be empty dict (edge type with no props — still valid)

    cols     = list(schema.keys())
    col_list = ", ".join(f"`{c}`" for c in cols)
    total    = 0
    batch: list[str] = []

    def flush():
        nonlocal total
        if not batch:
            return
        vals = ",\n  ".join(batch)
        if cols:
            ngql = f"INSERT EDGE IF NOT EXISTS `{etype}`({col_list}) VALUES\n  {vals};"
        else:
            ngql = f"INSERT EDGE IF NOT EXISTS `{etype}`() VALUES\n  {vals};"
        exec_batch(session, ngql, etype)
        total += len(batch)
        batch.clear()

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            if len(row) < 4:
                continue
            src, dst, rank_s, props_s = row[0], row[1], row[2], row[3]
            try:
                props: dict = json.loads(props_s)
            except (json.JSONDecodeError, IndexError):
                props = {}

            try:
                rank = int(rank_s)
            except (ValueError, TypeError):
                rank = 0

            vals = [fmt(props.get(c), schema[c]) for c in cols]
            src_e = src.replace("\\", "\\\\").replace('"', '\\"')
            dst_e = dst.replace("\\", "\\\\").replace('"', '\\"')

            if cols:
                batch.append(f'"{src_e}"->"{dst_e}"@{rank}:({", ".join(vals)})')
            else:
                batch.append(f'"{src_e}"->"{dst_e}"@{rank}:()')

            if len(batch) >= BATCH_SIZE:
                flush()

    flush()
    return total


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=== HoneyBadge NebulaGraph Data Loader ===")

    cfg = Config()
    cfg.max_connection_pool_size = 2
    cfg.timeout = 120_000   # 120 s per query

    pool = ConnectionPool()
    if not pool.init([(NEBULA_HOST, NEBULA_PORT)], cfg):
        print("ERROR: Cannot connect to NebulaGraph at "
              f"{NEBULA_HOST}:{NEBULA_PORT}")
        sys.exit(1)
    print(f"Connected to {NEBULA_HOST}:{NEBULA_PORT}")

    session = pool.get_session(NEBULA_USER, NEBULA_PASSWORD)
    r = session.execute(f"USE {NEBULA_SPACE}")
    if not r.is_succeeded():
        print(f"ERROR: Cannot USE space {NEBULA_SPACE}: {r.error_msg()}")
        session.release()
        pool.close()
        sys.exit(1)

    try:
        # ── Vertices ──────────────────────────────────────────────────────
        print("\n--- Loading Vertices ---")
        total_v = 0
        for vf in sorted(VERTEX_DIR.glob("*.csv")):
            print(f"  {vf.name:<40}", end="", flush=True)
            n = load_vertices(session, vf)
            total_v += n
            print(f"{n:>8,} rows")
        print(f"\n  Vertices total: {total_v:,}")

        # ── Edges ─────────────────────────────────────────────────────────
        print("\n--- Loading Edges ---")
        total_e = 0
        for ef in sorted(EDGE_DIR.glob("*.csv")):
            print(f"  {ef.name:<40}", end="", flush=True)
            n = load_edges(session, ef)
            total_e += n
            print(f"{n:>8,} rows")
        print(f"\n  Edges total: {total_e:,}")

        # ── Counts ────────────────────────────────────────────────────────
        print("\n--- Graph Counts ---")
        for q, label in [
            ("MATCH (v) RETURN count(v)", "Vertices"),
            ("MATCH ()-[e]->() RETURN count(e)", "Edges"),
        ]:
            r = session.execute(q)
            if r.is_succeeded() and r.row_size() > 0:
                print(f"  {label}: {r.rows()[0].values[0].get_iVal():,}")

    finally:
        session.release()
        pool.close()

    print("\n=== Load Complete ===")


if __name__ == "__main__":
    main()
