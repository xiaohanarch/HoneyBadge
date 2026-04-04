"""HoneyBadge Application Entry Point."""

import asyncio
import signal
import sys
from typing import Optional

import structlog
from pydantic_settings import BaseSettings

from honeybadge.core.constants import VERSION

logger = structlog.get_logger()


class AppSettings(BaseSettings):
    """Application settings from environment."""

    # LLM
    llm_endpoint: str = "http://localhost:8000/v1"
    llm_api_key: str = ""
    llm_model_name: str = "glm-4-flash"

    # NebulaGraph
    nebula_graphd_host: str = "localhost"
    nebula_graphd_port: int = 9669
    nebula_user: str = "root"
    nebula_password: str = "nebula"
    nebula_space: str = "honeybadge"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "honeybadge"
    postgres_password: str = ""
    postgres_db: str = "honeybadge_audit"

    # Matrix
    matrix_homeserver_url: str = "http://localhost:8008"
    matrix_bot_token: str = ""

    # Service
    service_host: str = "0.0.0.0"
    service_port: int = 8090


async def run_manager(settings: AppSettings) -> None:
    """Run the HiClaw Manager service."""
    from honeybadge.manager import HoneyBadgeManager

    logger.info("starting_manager", host=settings.service_host, port=settings.service_port)

    manager = HoneyBadgeManager(settings)
    await manager.start()

    # Wait for shutdown signal
    shutdown_event = asyncio.Event()

    def signal_handler(sig: signal.Signals) -> None:
        logger.info("shutdown_signal_received", signal=sig.name)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    await shutdown_event.wait()
    await manager.stop()
    logger.info("manager_stopped")


async def run_worker(settings: AppSettings, worker_group: str = "graph") -> None:
    """Run a HiClaw Worker service."""
    from honeybadge.worker import HoneyBadgeWorker

    logger.info("starting_worker", group=worker_group)

    worker = HoneyBadgeWorker(settings, worker_group)
    await worker.start()

    shutdown_event = asyncio.Event()

    def signal_handler(sig: signal.Signals) -> None:
        logger.info("shutdown_signal_received", signal=sig.name)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    await shutdown_event.wait()
    await worker.stop()
    logger.info("worker_stopped")


async def run_mcp_server(settings: AppSettings, server_type: str = "nebula") -> None:
    """Run an MCP Server."""
    from honeybadge.mcp import create_mcp_server

    logger.info("starting_mcp_server", type=server_type)

    server = await create_mcp_server(server_type, settings)
    await server.start()

    shutdown_event = asyncio.Event()

    def signal_handler(sig: signal.Signals) -> None:
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    await shutdown_event.wait()
    await server.stop()
    logger.info("mcp_server_stopped")


def main() -> None:
    """Main entry point."""
    import argparse

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging_level=20),
    )

    parser = argparse.ArgumentParser(description=f"HoneyBadge v{VERSION}")
    parser.add_argument("--version", action="version", version=f"v{VERSION}")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Manager command
    manager_parser = subparsers.add_parser("manager", help="Run the HiClaw Manager")

    # Worker command
    worker_parser = subparsers.add_parser("worker", help="Run a HiClaw Worker")
    worker_parser.add_argument("--group", default="graph", choices=["graph", "analytics", "mcp"])

    # MCP Server command
    mcp_parser = subparsers.add_parser("mcp", help="Run an MCP Server")
    mcp_parser.add_argument("--type", default="nebula", choices=["nebula", "llm", "redis"])

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    settings = AppSettings()

    if args.command == "manager":
        asyncio.run(run_manager(settings))
    elif args.command == "worker":
        asyncio.run(run_worker(settings, args.group))
    elif args.command == "mcp":
        asyncio.run(run_mcp_server(settings, args.type))


if __name__ == "__main__":
    main()
