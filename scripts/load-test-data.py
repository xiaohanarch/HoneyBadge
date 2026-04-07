"""Load CSV test data into NebulaGraph.

Usage:
    python scripts/load-test-data.py [--host HOST] [--port PORT]

Reads CSV files from deploy/test-data/csv/vertices/ and deploy/test-data/csv/edges/
and inserts them into the honeybadge space via nGQL INSERT statements.
"""

import argparse
import csv
import json
import os
import sys
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nebula3.Config import Config as NebulaConfig
from nebula3.gclient.net import ConnectionPool


def get_connection(host: str, port: int) -> ConnectionPool:
    config = NebulaConfig()
    config.max_connection_pool_size = 4
    config.timeout = 60000
    pool = ConnectionPool()
    ok = pool.init([(host, port)], config)
    if not ok:
        raise RuntimeError(f"Failed to connect to NebulaGraph at {host}:{port}")
    return pool


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
            print(f"  nGQL: {ngql[:200]}...")
            return False
        return True
    finally:
        session.release()


def escape_value(val: str) -> str:
    """Escape a string value for nGQL."""
    if val is None or val == "":
        return '""'
    return '"' + val.replace("\\", "\\\\").replace('"', '\\"') + '"'


def load_vertices(pool: ConnectionPool, csv_dir: str, space: str, batch_size: int = 50):
    """Load vertex CSV files."""
    files = sorted(f for f in os.listdir(csv_dir) if f.endswith(".csv"))
    for filename in files:
        tag_name = filename.replace(".csv", "")
        filepath = os.path.join(csv_dir, filename)

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print(f"  {tag_name}: 0 rows (skip)")
            continue

        # Parse first row to get property names
        sample_props = json.loads(rows[0]["properties"])
        prop_names = list(sample_props.keys())

        inserted = 0
        batch = []
        for row in rows:
            vid = row["vid"]
            props = json.loads(row["properties"])
            values = []
            for pname in prop_names:
                val = props.get(pname, "")
                if isinstance(val, bool):
                    values.append("true" if val else "false")
                elif isinstance(val, (int, float)):
                    values.append(str(val))
                elif val == "" or val is None:
                    values.append('""')
                else:
                    values.append(escape_value(str(val)))

            batch.append(f'"{vid}":({", ".join(values)})')

            if len(batch) >= batch_size:
                props_str = ", ".join(prop_names)
                ngql = f"INSERT VERTEX `{tag_name}`({props_str}) VALUES {', '.join(batch)};"
                if execute(pool, ngql, space):
                    inserted += len(batch)
                batch = []

        if batch:
            props_str = ", ".join(prop_names)
            ngql = f"INSERT VERTEX `{tag_name}`({props_str}) VALUES {', '.join(batch)};"
            if execute(pool, ngql, space):
                inserted += len(batch)

        print(f"  {tag_name}: {inserted}/{len(rows)} inserted")


def load_edges(pool: ConnectionPool, csv_dir: str, space: str, batch_size: int = 50):
    """Load edge CSV files."""
    files = sorted(f for f in os.listdir(csv_dir) if f.endswith(".csv"))
    for filename in files:
        edge_name = filename.replace(".csv", "")
        filepath = os.path.join(csv_dir, filename)

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print(f"  {edge_name}: 0 rows (skip)")
            continue

        # Parse first row to get property names
        sample_props = json.loads(rows[0]["properties"])
        prop_names = list(sample_props.keys())

        inserted = 0
        batch = []
        for row in rows:
            src = row["src_vid"]
            dst = row["dst_vid"]
            rank = row.get("rank", "0")
            props = json.loads(row["properties"])
            values = []
            for pname in prop_names:
                val = props.get(pname, "")
                if isinstance(val, bool):
                    values.append("true" if val else "false")
                elif isinstance(val, (int, float)):
                    values.append(str(val))
                elif val == "" or val is None:
                    values.append('""')
                else:
                    values.append(escape_value(str(val)))

            batch.append(f'"{src}"->"{dst}"@{rank}:({", ".join(values)})')

            if len(batch) >= batch_size:
                props_str = ", ".join(prop_names)
                ngql = f"INSERT EDGE `{edge_name}`({props_str}) VALUES {', '.join(batch)};"
                if execute(pool, ngql, space):
                    inserted += len(batch)
                batch = []

        if batch:
            props_str = ", ".join(prop_names)
            ngql = f"INSERT EDGE `{edge_name}`({props_str}) VALUES {', '.join(batch)};"
            if execute(pool, ngql, space):
                inserted += len(batch)

        print(f"  {edge_name}: {inserted}/{len(rows)} inserted")


def main():
    parser = argparse.ArgumentParser(description="Load test data into NebulaGraph")
    parser.add_argument("--host", default="localhost", help="NebulaGraph host")
    parser.add_argument("--port", type=int, default=9669, help="NebulaGraph port")
    parser.add_argument("--space", default="honeybadge", help="NebulaGraph space")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch insert size")
    args = parser.parse_args()

    base_dir = os.path.join(os.path.dirname(__file__), "..", "deploy", "test-data", "csv")
    vertex_dir = os.path.join(base_dir, "vertices")
    edge_dir = os.path.join(base_dir, "edges")

    print(f"Connecting to NebulaGraph at {args.host}:{args.port}...")
    pool = get_connection(args.host, args.port)

    print(f"\nLoading vertices into space '{args.space}'...")
    load_vertices(pool, vertex_dir, args.space, args.batch_size)

    print(f"\nLoading edges into space '{args.space}'...")
    load_edges(pool, edge_dir, args.space, args.batch_size)

    print("\nDone! Verifying...")
    session = pool.get_session("root", "nebula")
    try:
        session.execute(f"USE {args.space}")
        for tag in ["Supplier", "PurchaseOrder", "Invoice", "Item"]:
            r = session.execute(f"LOOKUP ON `{tag}` YIELD id(vertex) | LIMIT 1")
            count_r = session.execute(f'MATCH (n:{tag}) RETURN count(n) AS cnt')
            if count_r.is_succeeded() and count_r.row_size() > 0:
                cnt = count_r.row_values(0)[0].as_int()
                print(f"  {tag}: {cnt} vertices")
    finally:
        session.release()

    pool.close()
    print("\nTest data loaded successfully!")


if __name__ == "__main__":
    main()
