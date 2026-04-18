"""Synchronize live NebulaGraph schema with the authoritative .ngql definitions.

Reads `deploy/docker/nebula-schema.ngql` as the source of truth, compares it
against the live DB, and brings the DB in sync by:

  1. CREATE TAG  — for any tag defined in .ngql but missing from the DB.
  2. ALTER TAG ADD — for any property defined in .ngql but missing from an
     existing DB tag.

NebulaGraph limitation: ALTER TAG can only ADD one property per statement.

Replaces the two earlier, overlapping utilities:
  - alter-schema.py       (handled only ALTER for existing tags)
  - create-missing-tags.py (handled only CREATE for a hardcoded 11-tag list)

Usage:
    python scripts/sync-schema.py [--host HOST] [--port PORT] [--space NAME] [--dry-run]
"""

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nebula3.Config import Config as NebulaConfig
from nebula3.gclient.net import ConnectionPool


# ---------------------------------------------------------------------------
# .ngql parsing
# ---------------------------------------------------------------------------

def parse_ngql_tags(filepath: str) -> dict:
    """Parse CREATE TAG statements from a .ngql file.

    Returns: {tag_name: {prop_name: prop_definition, ...}, ...}
    prop_definition includes type and any defaults/constraints.
    Property order is preserved via insertion order of the dict.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    tags = {}
    pattern = r'CREATE TAG IF NOT EXISTS (\w+)\(([^;]+)\);'
    for match in re.finditer(pattern, content):
        tag_name = match.group(1)
        props_str = match.group(2)

        props = {}
        # Split on top-level commas (respect nested parens in DEFAULT values).
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
                _emit_prop(current, props)
                current = ""
            else:
                current += ch
        _emit_prop(current, props)
        tags[tag_name] = props

    return tags


def _emit_prop(raw: str, props: dict) -> None:
    prop_def = raw.strip()
    if not prop_def:
        return
    parts = prop_def.split(None, 1)
    if len(parts) >= 2:
        props[parts[0]] = parts[1]


def build_prop_clause(prop_name: str, prop_def: str) -> str:
    """Normalize a property clause for CREATE/ALTER.

    NebulaGraph requires DOUBLE/FLOAT DEFAULT values to be float literals
    (e.g. `DEFAULT 0.0`, not `DEFAULT 0`). This fixes that silently.
    """
    parts = prop_def.split()
    if len(parts) >= 3 and parts[0] in ("DOUBLE", "FLOAT") and parts[-2].upper() == "DEFAULT":
        try:
            val = float(parts[-1])
            if "." not in parts[-1]:
                parts[-1] = f"{val:.1f}"
            prop_def = " ".join(parts)
        except ValueError:
            pass
    return f"{prop_name} {prop_def}"


def build_create_statement(tag_name: str, props: dict) -> str:
    """Build a full CREATE TAG IF NOT EXISTS statement from parsed props."""
    clauses = [build_prop_clause(p, d) for p, d in props.items()]
    body = ",\n    ".join(clauses)
    return f"CREATE TAG IF NOT EXISTS `{tag_name}` (\n    {body}\n);"


# ---------------------------------------------------------------------------
# DB access
# ---------------------------------------------------------------------------

def get_connection(host: str, port: int) -> ConnectionPool:
    config = NebulaConfig()
    config.max_connection_pool_size = 10
    config.timeout = 120000
    pool = ConnectionPool()
    if not pool.init([(host, port)], config):
        raise RuntimeError(f"Failed to connect to NebulaGraph at {host}:{port}")
    return pool


def fetch_db_tags(pool: ConnectionPool, space: str) -> dict:
    """Return {tag_name: set_of_prop_names} for every tag in `space`."""
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sync NebulaGraph tags with the authoritative .ngql file "
                    "(CREATE missing tags + ALTER TAG ADD missing properties)."
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=9669)
    parser.add_argument("--space", default="honeybadge")
    parser.add_argument(
        "--ngql",
        default=os.path.join(os.path.dirname(__file__), "..", "deploy", "docker", "nebula-schema.ngql"),
        help="Path to the authoritative .ngql schema file",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print DDL without executing")
    args = parser.parse_args()

    print(f"Parsing {args.ngql}...")
    file_tags = parse_ngql_tags(args.ngql)
    print(f"  Found {len(file_tags)} tags in .ngql file\n")

    print(f"Connecting to NebulaGraph at {args.host}:{args.port}...")
    pool = get_connection(args.host, args.port)

    print(f"Fetching current schema from space '{args.space}'...")
    db_tags = fetch_db_tags(pool, args.space)
    print(f"  Found {len(db_tags)} tags in DB\n")

    # Build work plan
    create_statements = []  # [(tag_name, stmt), ...]
    alter_statements = []   # [(tag_name, prop_name, stmt), ...]

    for tag_name, file_props in sorted(file_tags.items()):
        if tag_name not in db_tags:
            stmt = build_create_statement(tag_name, file_props)
            create_statements.append((tag_name, stmt))
            print(f"  {tag_name}: NEW ({len(file_props)} props) → CREATE TAG")
            continue

        db_props = db_tags[tag_name]
        missing = {p: d for p, d in file_props.items() if p not in db_props}

        if not missing:
            print(f"  {tag_name}: OK ({len(db_props)} props, all match)")
            continue

        print(f"  {tag_name}: {len(missing)} missing properties: {sorted(missing.keys())}")
        for prop_name, prop_def in sorted(missing.items()):
            stmt = f'ALTER TAG `{tag_name}` ADD ({build_prop_clause(prop_name, prop_def)});'
            alter_statements.append((tag_name, prop_name, stmt))

    print(f"\nWork plan: {len(create_statements)} CREATE TAG, "
          f"{len(alter_statements)} ALTER TAG ADD")

    if not create_statements and not alter_statements:
        print("Schema already in sync. Nothing to do.")
        pool.close()
        return

    if args.dry_run:
        print("\n=== DRY RUN — statements that would be executed ===")
        for tag, stmt in create_statements:
            print(f"\n-- CREATE {tag}")
            print(stmt)
        for tag, prop, stmt in alter_statements:
            print(f"  {stmt}")
        pool.close()
        return

    # Execute
    session = pool.get_session("root", "nebula")
    success = 0
    failed = 0
    try:
        session.execute(f"USE {args.space}")

        if create_statements:
            print(f"\nExecuting {len(create_statements)} CREATE TAG statements...")
            for tag, stmt in create_statements:
                r = session.execute(stmt)
                if r.is_succeeded():
                    success += 1
                    print(f"  OK: CREATE {tag}")
                else:
                    failed += 1
                    print(f"  FAIL: CREATE {tag} — {r.error_msg()}")
                time.sleep(0.1)

        if alter_statements:
            print(f"\nExecuting {len(alter_statements)} ALTER TAG statements...")
            for tag, prop, stmt in alter_statements:
                r = session.execute(stmt)
                if r.is_succeeded():
                    success += 1
                    print(f"  OK: ALTER {tag}.{prop}")
                else:
                    failed += 1
                    print(f"  FAIL: ALTER {tag}.{prop} — {r.error_msg()}")
                    print(f"        {stmt}")
                time.sleep(0.1)
    finally:
        session.release()

    print(f"\nResults: {success} succeeded, {failed} failed")

    # Verify
    print("\nVerifying updated schema...")
    db_tags_after = fetch_db_tags(pool, args.space)
    mismatches = 0
    for tag_name, file_props in sorted(file_tags.items()):
        if tag_name not in db_tags_after:
            print(f"  {tag_name}: STILL MISSING")
            mismatches += 1
            continue
        db_count = len(db_tags_after[tag_name])
        file_count = len(file_props)
        if db_count != file_count:
            print(f"  {tag_name}: MISMATCH (db={db_count}, file={file_count})")
            mismatches += 1
    if mismatches == 0:
        print("  All tags in sync.")

    pool.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
