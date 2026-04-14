"""Compare NebulaGraph DB schema with .ngql file definitions and apply ALTER TAG ADD.

Parses deploy/docker/nebula-schema.ngql to extract the authoritative tag definitions,
then queries the live DB to find missing properties, and executes ALTER TAG ADD for each.

NebulaGraph limitation: ALTER TAG can only ADD one property at a time.

Usage:
    python scripts/alter-schema.py [--host HOST] [--port PORT] [--dry-run]
"""

import argparse
import re
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nebula3.Config import Config as NebulaConfig
from nebula3.gclient.net import ConnectionPool


def parse_ngql_tags(filepath: str) -> dict:
    """Parse CREATE TAG statements from .ngql file.

    Returns: {tag_name: {prop_name: prop_definition, ...}, ...}
    prop_definition includes type and any defaults/constraints.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    tags = {}
    # Match CREATE TAG IF NOT EXISTS TagName(prop1 TYPE ..., prop2 TYPE ..., ...);
    pattern = r'CREATE TAG IF NOT EXISTS (\w+)\(([^;]+)\);'
    for match in re.finditer(pattern, content):
        tag_name = match.group(1)
        props_str = match.group(2)

        props = {}
        # Parse individual property definitions
        # Each prop is like: prop_name TYPE [NOT NULL] [DEFAULT value]
        # We need to handle nested parentheses in DEFAULT values and commas within strings
        depth = 0
        current = ""
        for ch in props_str:
            if ch == '(':
                depth += 1
                current += ch
            elif ch == ')':
                depth -= 1
                current += ch
            elif ch == ',' and depth == 0:
                prop_def = current.strip()
                if prop_def:
                    parts = prop_def.split(None, 1)
                    if len(parts) >= 2:
                        props[parts[0]] = parts[1]
                current = ""
            else:
                current += ch
        # Don't forget the last property
        prop_def = current.strip()
        if prop_def:
            parts = prop_def.split(None, 1)
            if len(parts) >= 2:
                props[parts[0]] = parts[1]

        tags[tag_name] = props

    return tags


def parse_prop_type(prop_def: str) -> str:
    """Extract just the type from a property definition like 'STRING NOT NULL DEFAULT "CNY"'."""
    # The type is the first word
    parts = prop_def.strip().split()
    return parts[0] if parts else "STRING"


def build_alter_prop(prop_name: str, prop_def: str) -> str:
    """Build the ALTER TAG ADD clause for one property.

    Input: prop_name='tax_amount', prop_def='DOUBLE DEFAULT 0'
    Output: 'tax_amount DOUBLE DEFAULT 0.0'

    NebulaGraph requires DOUBLE defaults to be float literals (0.0 not 0).
    """
    # Fix DOUBLE/FLOAT DEFAULT 0 → DEFAULT 0.0
    parts = prop_def.split()
    if len(parts) >= 3 and parts[0] in ("DOUBLE", "FLOAT") and parts[-2].upper() == "DEFAULT":
        try:
            val = float(parts[-1])
            if "." not in parts[-1]:
                parts[-1] = f"{val:.1f}"
        except ValueError:
            pass
        prop_def = " ".join(parts)
    return f"{prop_name} {prop_def}"


def get_connection(host: str, port: int) -> ConnectionPool:
    config = NebulaConfig()
    config.max_connection_pool_size = 10
    config.timeout = 120000
    pool = ConnectionPool()
    ok = pool.init([(host, port)], config)
    if not ok:
        raise RuntimeError(f"Failed to connect to NebulaGraph at {host}:{port}")
    return pool


def fetch_db_tags(pool: ConnectionPool, space: str) -> dict:
    """Fetch current tag schemas from DB. Returns {tag_name: set_of_prop_names}."""
    session = pool.get_session("root", "nebula")
    try:
        session.execute(f"USE {space}")
        db_tags = {}
        r = session.execute("SHOW TAGS")
        for i in range(r.row_size()):
            tag = r.row_values(i)[0].as_string()
            r2 = session.execute(f"DESCRIBE TAG `{tag}`")
            if r2.is_succeeded():
                props = set()
                for j in range(r2.row_size()):
                    props.add(r2.row_values(j)[0].as_string())
                db_tags[tag] = props
        return db_tags
    finally:
        session.release()


def main():
    parser = argparse.ArgumentParser(description="Alter NebulaGraph tags to match .ngql definitions")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=9669)
    parser.add_argument("--space", default="honeybadge")
    parser.add_argument("--dry-run", action="store_true", help="Print ALTER statements without executing")
    args = parser.parse_args()

    ngql_path = os.path.join(os.path.dirname(__file__), "..", "deploy", "docker", "nebula-schema.ngql")
    print(f"Parsing {ngql_path}...")
    file_tags = parse_ngql_tags(ngql_path)
    print(f"  Found {len(file_tags)} tags in .ngql file\n")

    print(f"Connecting to NebulaGraph at {args.host}:{args.port}...")
    pool = get_connection(args.host, args.port)

    print(f"Fetching current schema from space '{args.space}'...")
    db_tags = fetch_db_tags(pool, args.space)
    print(f"  Found {len(db_tags)} tags in DB\n")

    # Compare and generate ALTER statements
    alter_statements = []
    for tag_name, file_props in sorted(file_tags.items()):
        if tag_name not in db_tags:
            print(f"  {tag_name}: NOT IN DB (needs CREATE TAG, not ALTER)")
            continue

        db_props = db_tags[tag_name]
        missing = {p: d for p, d in file_props.items() if p not in db_props}

        if not missing:
            print(f"  {tag_name}: OK ({len(db_props)} props, all match)")
            continue

        print(f"  {tag_name}: {len(missing)} missing properties: {sorted(missing.keys())}")
        for prop_name, prop_def in sorted(missing.items()):
            stmt = f'ALTER TAG `{tag_name}` ADD ({build_alter_prop(prop_name, prop_def)});'
            alter_statements.append((tag_name, prop_name, stmt))

    print(f"\nTotal ALTER TAG ADD statements: {len(alter_statements)}")

    if not alter_statements:
        print("Nothing to do!")
        pool.close()
        return

    if args.dry_run:
        print("\n=== DRY RUN — statements that would be executed ===")
        for tag, prop, stmt in alter_statements:
            print(f"  {stmt}")
        pool.close()
        return

    # Execute
    print(f"\nExecuting {len(alter_statements)} ALTER TAG statements...")
    session = pool.get_session("root", "nebula")
    try:
        session.execute(f"USE {args.space}")
        success = 0
        failed = 0
        for tag, prop, stmt in alter_statements:
            r = session.execute(stmt)
            if r.is_succeeded():
                success += 1
                print(f"  OK: {tag}.{prop}")
            else:
                failed += 1
                print(f"  FAIL: {tag}.{prop} — {r.error_msg()}")
                print(f"        {stmt}")
            # Small delay to avoid overwhelming the DB
            time.sleep(0.1)
    finally:
        session.release()

    print(f"\nResults: {success} succeeded, {failed} failed")

    # Verify
    print("\nVerifying updated schema...")
    db_tags_after = fetch_db_tags(pool, args.space)
    for tag_name, file_props in sorted(file_tags.items()):
        if tag_name not in db_tags_after:
            continue
        db_count = len(db_tags_after[tag_name])
        file_count = len(file_props)
        status = "OK" if db_count == file_count else f"MISMATCH (db={db_count}, file={file_count})"
        if db_count != file_count:
            print(f"  {tag_name}: {status}")

    pool.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
