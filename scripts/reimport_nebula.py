#!/usr/bin/env python3
"""Re-import CSV data into a clean NebulaGraph space."""
import asyncio
import csv
import sys
from datetime import datetime as _dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from honeybadge.db.nebula import NebulaGraphClient
from honeybadge.etl.tag_prop_types import get_edge_prop_type, get_tag_prop_type

BATCH_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("import/USASPENDING-5Y")
BATCH_SIZE = 200
SPACE = "honeybadge"


def format_ngql_value(val: str, prop_type: str) -> str:
    if val == "" or val is None:
        return "null"
    ut = prop_type.upper()
    if ut in ("INT", "INT64", "BIGINT", "INTEGER", "INT32"):
        return str(int(float(val)))
    if ut in ("DOUBLE", "FLOAT", "DECIMAL"):
        return str(float(val))
    if ut == "BOOL":
        return "true" if val.lower() in ("true", "1", "yes") else "false"
    if ut == "TIMESTAMP":
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return str(int(_dt.strptime(val, fmt).timestamp()))
            except ValueError:
                pass
        try:
            return str(int(float(val)))
        except ValueError:
            return "null"
    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


async def main():
    client = NebulaGraphClient(host="localhost", port=9669, user="root", password="nebula")
    await client.connect()

    total_v = 0
    total_e = 0

    # Import vertices
    for vfile in sorted(BATCH_DIR.glob("vertex_*.csv")):
        tag = vfile.stem.replace("vertex_", "")
        with open(vfile, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            prop_names = header[1:]
            batch = []
            for row in reader:
                vid = row[0]
                vals = [
                    format_ngql_value(
                        val,
                        get_tag_prop_type(tag, prop_names[i] if i < len(prop_names) else ""),
                    )
                    for i, val in enumerate(row[1:])
                ]
                batch.append(f'"{vid}":({", ".join(vals)})')
                if len(batch) >= BATCH_SIZE:
                    ngql = f"INSERT VERTEX {tag}({', '.join(prop_names)}) VALUES {', '.join(batch)};"
                    r = await client.execute(ngql, space=SPACE)
                    if not r.success:
                        print(f"ERROR vertex {tag}: {r.error_message[:200]}")
                    total_v += len(batch)
                    batch = []
            if batch:
                ngql = f"INSERT VERTEX {tag}({', '.join(prop_names)}) VALUES {', '.join(batch)};"
                r = await client.execute(ngql, space=SPACE)
                if not r.success:
                    print(f"ERROR vertex {tag}: {r.error_message[:200]}")
                total_v += len(batch)
        print(f"  vertex {tag}: done (running total: {total_v})")

    # Import edges
    for efile in sorted(BATCH_DIR.glob("edge_*.csv")):
        etype = efile.stem.replace("edge_", "")
        with open(efile, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            prop_names = header[2:]
            batch = []
            for row in reader:
                src, dst = row[0], row[1]
                vals = [
                    format_ngql_value(
                        val,
                        get_edge_prop_type(etype, prop_names[i] if i < len(prop_names) else ""),
                    )
                    for i, val in enumerate(row[2:])
                ]
                values_str = ", ".join(vals) if vals else ""
                batch.append(f'"{src}"->"{dst}":({values_str})')
                if len(batch) >= BATCH_SIZE:
                    prop_clause = f"({', '.join(prop_names)})" if prop_names else ""
                    ngql = f"INSERT EDGE {etype}{prop_clause} VALUES {', '.join(batch)};"
                    r = await client.execute(ngql, space=SPACE)
                    if not r.success:
                        print(f"ERROR edge {etype}: {r.error_message[:200]}")
                    total_e += len(batch)
                    batch = []
            if batch:
                prop_clause = f"({', '.join(prop_names)})" if prop_names else ""
                ngql = f"INSERT EDGE {etype}{prop_clause} VALUES {', '.join(batch)};"
                r = await client.execute(ngql, space=SPACE)
                if not r.success:
                    print(f"ERROR edge {etype}: {r.error_message[:200]}")
                total_e += len(batch)
        print(f"  edge {etype}: done (running total: {total_e})")

    await client.disconnect()
    print(f"\nComplete: {total_v} vertices, {total_e} edges imported")


if __name__ == "__main__":
    asyncio.run(main())
