"""CLI entry point for the ETL subsystem.

Usage
-----
Run on a cron schedule (foreground, blocks forever):

    python -m honeybadge.etl --config deploy/docker/etl-config.yaml

Run a single pipeline invocation and exit:

    python -m honeybadge.etl --config deploy/docker/etl-config.yaml --run-once
"""

from __future__ import annotations

import argparse
import asyncio

from honeybadge.etl.scheduler import run_once, run_scheduler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HoneyBadge ETL scheduler / one-shot runner",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="deploy/docker/etl-config.yaml",
        help="Path to the ETL YAML config file",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single pipeline invocation and exit",
    )
    args = parser.parse_args()

    if args.run_once:
        batch_id = asyncio.run(run_once(args.config))
        print(f"Pipeline run completed. batch_id={batch_id}")
        return 0

    try:
        asyncio.run(run_scheduler(args.config))
    except KeyboardInterrupt:
        print("\nScheduler stopped by user.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
