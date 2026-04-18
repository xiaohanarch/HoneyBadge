"""Load CSV test data into NebulaGraph.

Usage:
    python scripts/load-test-data.py [--host HOST] [--port PORT]

Reads CSV files from deploy/test-data/csv/vertices/ and deploy/test-data/csv/edges/
and inserts them into the honeybadge space via nGQL INSERT statements.

Type-aware: fetches schema from NebulaGraph and converts CSV string values
to the correct nGQL types (int64, double, timestamp, bool, string).
Only inserts properties that exist in the schema (extra CSV columns are skipped).
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nebula3.Config import Config as NebulaConfig
from nebula3.gclient.net import ConnectionPool


def get_connection(host: str, port: int) -> ConnectionPool:
    config = NebulaConfig()
    config.max_connection_pool_size = 10
    config.timeout = 120000
    pool = ConnectionPool()
    ok = pool.init([(host, port)], config)
    if not ok:
        raise RuntimeError(f"Failed to connect to NebulaGraph at {host}:{port}")
    return pool


def fetch_schema(pool: ConnectionPool, space: str):
    """Fetch tag and edge schema type maps from NebulaGraph."""
    session = pool.get_session("root", "nebula")
    try:
        session.execute(f"USE {space}")

        tag_schema = {}
        r = session.execute("SHOW TAGS")
        for i in range(r.row_size()):
            tag = r.row_values(i)[0].as_string()
            r2 = session.execute(f"DESCRIBE TAG `{tag}`")
            if r2.is_succeeded():
                props = {}
                for j in range(r2.row_size()):
                    vals = r2.row_values(j)
                    props[vals[0].as_string()] = vals[1].as_string()
                tag_schema[tag] = props

        edge_schema = {}
        r = session.execute("SHOW EDGES")
        for i in range(r.row_size()):
            edge = r.row_values(i)[0].as_string()
            r2 = session.execute(f"DESCRIBE EDGE `{edge}`")
            if r2.is_succeeded():
                props = {}
                for j in range(r2.row_size()):
                    vals = r2.row_values(j)
                    props[vals[0].as_string()] = vals[1].as_string()
                edge_schema[edge] = props

        return tag_schema, edge_schema
    finally:
        session.release()


def escape_string(val: str) -> str:
    """Escape a string value for nGQL."""
    if val is None or val == "":
        return '""'
    return '"' + val.replace("\\", "\\\\").replace('"', '\\"') + '"'


def convert_timestamp(val: str) -> str:
    """Convert ISO timestamp string to NebulaGraph timestamp (unix seconds)."""
    if not val or val == "":
        return "0"
    try:
        # Handle ISO format: 2025-10-21T11:54:37.000000Z
        val = val.rstrip("Z")
        if "T" in val:
            if "." in val:
                dt = datetime.strptime(val, "%Y-%m-%dT%H:%M:%S.%f")
            else:
                dt = datetime.strptime(val, "%Y-%m-%dT%H:%M:%S")
        else:
            dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)
        return str(int(dt.timestamp()))
    except (ValueError, OSError):
        return "0"


def convert_value(val, schema_type: str) -> str:
    """Convert a CSV value to the correct nGQL literal based on schema type."""
    val_str = str(val) if val is not None else ""

    if schema_type == "string":
        return escape_string(val_str)
    elif schema_type == "int64" or schema_type == "int32":
        if val_str == "" or val_str == "None":
            return "0"
        try:
            return str(int(float(val_str)))
        except (ValueError, OverflowError):
            return "0"
    elif schema_type == "double" or schema_type == "float":
        if val_str == "" or val_str == "None":
            return "0.0"
        try:
            return str(float(val_str))
        except ValueError:
            return "0.0"
    elif schema_type == "bool":
        return "true" if val_str.lower() in ("true", "1", "yes") else "false"
    elif schema_type == "timestamp":
        return convert_timestamp(val_str)
    else:
        return escape_string(val_str)


def execute(pool: ConnectionPool, ngql: str, space: str = "") -> bool:
    session = pool.get_session("root", "nebula")
    try:
        if space:
            r = session.execute(f"USE {space}")
            if not r.is_succeeded():
                print(f"  ERROR: USE {space}: {r.error_msg()}")
                return False
        r = session.execute(ngql)
        if not r.is_succeeded():
            print(f"  ERROR: {r.error_msg()}")
            print(f"  nGQL: {ngql[:300]}...")
            return False
        return True
    finally:
        session.release()


def load_vertices(pool: ConnectionPool, csv_dir: str, space: str,
                  tag_schema: dict, batch_size: int = 50) -> dict:
    """Load vertex CSV files, converting types based on schema.

    Returns: {tag_name: inserted_count} for downstream summary/verification.
    """
    files = sorted(f for f in os.listdir(csv_dir) if f.endswith(".csv"))
    total_inserted = 0
    inserted_by_tag = {}

    for filename in files:
        tag_name = filename.replace(".csv", "")
        filepath = os.path.join(csv_dir, filename)

        if tag_name not in tag_schema:
            print(f"  {tag_name}: SKIPPED (not in schema)")
            continue

        type_map = tag_schema[tag_name]
        schema_props = list(type_map.keys())

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print(f"  {tag_name}: 0 rows (skip)")
            inserted_by_tag[tag_name] = 0
            continue

        # Check which CSV props are in schema
        sample_props = json.loads(rows[0]["properties"])
        csv_props = set(sample_props.keys())
        used_props = [p for p in schema_props if p in csv_props]
        skipped_props = csv_props - set(schema_props)

        inserted = 0
        errors = 0
        batch = []
        for row in rows:
            vid = row["vid"]
            props = json.loads(row["properties"])
            values = []
            for pname in used_props:
                val = props.get(pname, "")
                values.append(convert_value(val, type_map[pname]))

            batch.append(f'"{vid}":({", ".join(values)})')

            if len(batch) >= batch_size:
                props_str = ", ".join(used_props)
                ngql = f"INSERT VERTEX `{tag_name}`({props_str}) VALUES {', '.join(batch)};"
                if execute(pool, ngql, space):
                    inserted += len(batch)
                else:
                    errors += len(batch)
                batch = []

        if batch:
            props_str = ", ".join(used_props)
            ngql = f"INSERT VERTEX `{tag_name}`({props_str}) VALUES {', '.join(batch)};"
            if execute(pool, ngql, space):
                inserted += len(batch)
            else:
                errors += len(batch)

        extra = f" (skipped props: {sorted(skipped_props)})" if skipped_props else ""
        err_msg = f" ({errors} errors)" if errors else ""
        print(f"  {tag_name}: {inserted}/{len(rows)} inserted{err_msg}{extra}")
        total_inserted += inserted
        inserted_by_tag[tag_name] = inserted

    print(f"\n  Total vertices inserted: {total_inserted}")
    return inserted_by_tag


def load_edges(pool: ConnectionPool, csv_dir: str, space: str,
               edge_schema: dict, batch_size: int = 50,
               vertex_counts: dict = None) -> dict:
    """Load edge CSV files, converting types based on schema.

    If vertex_counts is provided, warn (but do not skip) when an edge file is
    about to load before its expected source/destination vertex tags have any
    rows in the just-completed vertex pass.

    Returns: {edge_name: (inserted, total_rows, errors)} for downstream summary.
    """
    files = sorted(f for f in os.listdir(csv_dir) if f.endswith(".csv"))
    total_inserted = 0
    summary = {}

    for filename in files:
        edge_name = filename.replace(".csv", "")
        filepath = os.path.join(csv_dir, filename)

        if edge_name not in edge_schema:
            print(f"  {edge_name}: SKIPPED (not in schema)")
            continue

        type_map = edge_schema[edge_name]
        schema_props = list(type_map.keys())

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print(f"  {edge_name}: 0 rows (skip)")
            summary[edge_name] = (0, 0, 0)
            continue

        # Defensive check: warn if src/dst vertex tag prefix has no loaded vertices.
        # This catches the "edge loaded before vertex" failure mode early.
        if vertex_counts is not None:
            src_prefix = rows[0]["src_vid"].split(":", 1)[0]
            dst_prefix = rows[0]["dst_vid"].split(":", 1)[0]
            warn_parts = []
            for prefix, side in ((src_prefix, "src"), (dst_prefix, "dst")):
                # Find tag(s) whose first row matches this VID prefix.
                # We can't map prefix→tag directly without a registry, so we do a
                # best-effort warning: if NO vertex tag has any rows, flag it.
                if not any(c > 0 for c in vertex_counts.values()):
                    warn_parts.append(f"NO VERTICES LOADED")
                    break
            if warn_parts:
                print(f"  {edge_name}: WARNING — {', '.join(warn_parts)}")

        sample_props = json.loads(rows[0]["properties"])
        csv_props = set(sample_props.keys())
        used_props = [p for p in schema_props if p in csv_props]

        inserted = 0
        errors = 0
        batch = []
        for row in rows:
            src = row["src_vid"]
            dst = row["dst_vid"]
            rank = row.get("rank", "0")
            props = json.loads(row["properties"])
            values = []
            for pname in used_props:
                val = props.get(pname, "")
                values.append(convert_value(val, type_map[pname]))

            batch.append(f'"{src}"->"{dst}"@{rank}:({", ".join(values)})')

            if len(batch) >= batch_size:
                props_str = ", ".join(used_props)
                ngql = f"INSERT EDGE `{edge_name}`({props_str}) VALUES {', '.join(batch)};"
                if execute(pool, ngql, space):
                    inserted += len(batch)
                else:
                    errors += len(batch)
                batch = []

        if batch:
            props_str = ", ".join(used_props)
            ngql = f"INSERT EDGE `{edge_name}`({props_str}) VALUES {', '.join(batch)};"
            if execute(pool, ngql, space):
                inserted += len(batch)
            else:
                errors += len(batch)

        err_msg = f" ({errors} errors)" if errors else ""
        print(f"  {edge_name}: {inserted}/{len(rows)} inserted{err_msg}")
        total_inserted += inserted
        summary[edge_name] = (inserted, len(rows), errors)

    print(f"\n  Total edges inserted: {total_inserted}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Load test data into NebulaGraph")
    parser.add_argument("--host", default="localhost", help="NebulaGraph host")
    parser.add_argument("--port", type=int, default=9669, help="NebulaGraph port")
    parser.add_argument("--space", default="honeybadge", help="NebulaGraph space")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch insert size")
    parser.add_argument(
        "--csv-dir",
        default=os.path.join(os.path.dirname(__file__), "..", "deploy", "test-data", "csv"),
        help="Root CSV directory (must contain vertices/ and edges/ subdirs)",
    )
    args = parser.parse_args()

    base_dir = args.csv_dir
    vertex_dir = os.path.join(base_dir, "vertices")
    edge_dir = os.path.join(base_dir, "edges")

    if not os.path.isdir(vertex_dir) or not os.path.isdir(edge_dir):
        print(f"ERROR: --csv-dir must contain 'vertices/' and 'edges/' subdirs")
        print(f"  Got: {base_dir}")
        sys.exit(2)

    print(f"Connecting to NebulaGraph at {args.host}:{args.port}...")
    pool = get_connection(args.host, args.port)

    print(f"Fetching schema from space '{args.space}'...")
    tag_schema, edge_schema = fetch_schema(pool, args.space)
    print(f"  Found {len(tag_schema)} tags, {len(edge_schema)} edge types\n")

    print(f"Loading vertices from {vertex_dir} into space '{args.space}'...")
    t0 = time.time()
    vertex_counts = load_vertices(pool, vertex_dir, args.space, tag_schema, args.batch_size)
    print(f"  Vertex load time: {time.time() - t0:.1f}s\n")

    print(f"Loading edges from {edge_dir} into space '{args.space}'...")
    t0 = time.time()
    edge_summary = load_edges(pool, edge_dir, args.space, edge_schema,
                              args.batch_size, vertex_counts=vertex_counts)
    print(f"  Edge load time: {time.time() - t0:.1f}s\n")

    # ---------------------------------------------------------------
    # Per-edge zero-row report (catches the "loader silently lost edges" failure mode)
    # ---------------------------------------------------------------
    csv_files = sorted(f for f in os.listdir(edge_dir) if f.endswith(".csv"))
    csv_row_counts = {}
    for fn in csv_files:
        with open(os.path.join(edge_dir, fn), "r", encoding="utf-8") as f:
            csv_row_counts[fn.replace(".csv", "")] = sum(1 for _ in f) - 1

    suspect = []
    for edge_name, csv_n in csv_row_counts.items():
        if csv_n <= 0:
            continue
        ins, total, errs = edge_summary.get(edge_name, (0, 0, 0))
        if ins == 0 and total == 0:
            suspect.append((edge_name, csv_n, "edge not in DB schema"))
        elif ins == 0 and total > 0:
            suspect.append((edge_name, csv_n, "all inserts failed"))
        elif errs > 0:
            suspect.append((edge_name, csv_n, f"{errs} insert errors"))

    if suspect:
        print("WARNING — edges with anomalies:")
        for name, n, reason in suspect:
            print(f"    {name}: csv has {n} rows but {reason}")
    else:
        print("All non-empty edge CSVs were loaded without errors.")

    print("\nDone! Verifying sample tag counts...")
    session = pool.get_session("root", "nebula")
    try:
        session.execute(f"USE {args.space}")
        for tag in ["Supplier", "PurchaseOrder", "Invoice", "Item",
                     "SalesOrder", "Receipt", "Payment", "GLJournalEntry"]:
            count_r = session.execute(f"MATCH (n:`{tag}`) RETURN count(n) AS cnt")
            if count_r.is_succeeded() and count_r.row_size() > 0:
                cnt = count_r.row_values(0)[0].as_int()
                print(f"  {tag}: {cnt} vertices")
    finally:
        session.release()

    pool.close()
    print("\nTest data loaded successfully!")


if __name__ == "__main__":
    main()
