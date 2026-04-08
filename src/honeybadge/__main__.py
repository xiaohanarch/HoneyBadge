"""HoneyBadge entry point.

Commands:
  nebula-mcp    Run NebulaGraph MCP Server (SSE)
  audit-mcp     Run Audit Log MCP Server (SSE)
  cache-mcp     Run Redis Cache MCP Server (SSE)
  manager       Run HiClaw Manager Matrix bot
  worker        Run HiClaw Worker Matrix bot (set WORKER_TYPE env var)
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time

from honeybadge.core.constants import VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=f"HoneyBadge v{VERSION}")
    parser.add_argument("--version", action="version", version=f"v{VERSION}")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("nebula-mcp", help="Run NebulaGraph MCP Server")
    subparsers.add_parser("audit-mcp", help="Run Audit Log MCP Server")
    subparsers.add_parser("cache-mcp", help="Run Redis Cache MCP Server")
    subparsers.add_parser("manager", help="Run HiClaw Manager Matrix bot")
    subparsers.add_parser("worker", help="Run HiClaw Worker Matrix bot")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "nebula-mcp":
        sys.path.insert(0, "mcp-servers/honeybadge-nebula-mcp")
        from server import mcp  # type: ignore[import]
        mcp.run(transport="sse")
    elif args.command == "audit-mcp":
        sys.path.insert(0, "mcp-servers/honeybadge-audit-mcp")
        from server import mcp  # type: ignore[import]
        mcp.run(transport="sse")
    elif args.command == "cache-mcp":
        sys.path.insert(0, "mcp-servers/honeybadge-cache-mcp")
        from server import mcp  # type: ignore[import]
        mcp.run(transport="sse")
    elif args.command == "manager":
        asyncio.run(_run_manager())
    elif args.command == "worker":
        asyncio.run(_run_worker())


# =============================================================================
# MCP helper — shared by both Manager and Worker
# =============================================================================

async def _call_mcp_tool(base_url: str, tool_name: str, arguments: dict,
                          timeout: float = 30.0) -> dict:
    """Call an MCP tool over SSE and return the parsed JSON result."""
    from mcp.client.sse import sse_client
    from mcp.client.session import ClientSession

    async with sse_client(f"{base_url}/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=timeout,
            )
    # FastMCP returns TextContent; parse JSON if possible
    if result.content and hasattr(result.content[0], "text"):
        try:
            return json.loads(result.content[0].text)
        except json.JSONDecodeError:
            return {"text": result.content[0].text}
    return {}


# =============================================================================
# HiClaw Manager — Matrix bot
# =============================================================================

# Intent classifier: analytics-related keywords → analytics-worker
_ANALYTICS_RE = re.compile(r"分析|趋势|对比|统计|异常|检测|fraud", re.IGNORECASE)


async def _run_manager() -> None:
    """HiClaw Manager Matrix bot.

    Connects to the Matrix homeserver, auto-accepts room invites from the
    gateway bot, and listens for gateway_query messages. Routes each query
    to the appropriate worker room based on intent classification.

    Environment variables:
      MATRIX_HOMESERVER_URL   e.g. http://matrix:8008
      MATRIX_USER_ID          e.g. @honeybadge-manager:matrix.local
      MATRIX_USER_PASSWORD    manager account password
    """
    import structlog
    logger = structlog.get_logger()

    try:
        from nio import AsyncClient, InviteMemberEvent, LoginResponse, RoomMessage, RoomCreateResponse
    except ImportError:
        print("ERROR: matrix-nio is not installed. Add it to requirements.txt.", file=sys.stderr)
        sys.exit(1)

    homeserver_url = os.environ.get("MATRIX_HOMESERVER_URL", "http://localhost:8008")
    user_id = os.environ.get("MATRIX_USER_ID", "@honeybadge-manager:matrix.local")
    password = os.environ.get("MATRIX_USER_PASSWORD", "")

    # Extract server name from user_id (e.g. "matrix.local")
    server_name = user_id.split(":")[-1]

    client = AsyncClient(homeserver_url, user_id)

    # worker_matrix_user_id → room_id (DM rooms we've opened with workers)
    _worker_rooms: dict[str, str] = {}
    # trace_id → gateway_room_id (pending tasks waiting for worker response)
    _pending_tasks: dict[str, str] = {}

    async def on_invite(room: object, event: object) -> None:
        """Auto-accept invites so the gateway can open DM rooms with us."""
        room_id = getattr(room, "room_id", None)
        if room_id:
            await client.join(room_id)  # type: ignore[union-attr]
            logger.info("manager_joined_room", room_id=room_id)

    async def on_message(room: object, event: object) -> None:
        """Handle incoming m.room.message events from gateway or workers."""
        sender = getattr(event, "sender", "")
        if sender == user_id:
            return  # ignore own messages

        try:
            raw = event.source.get("content", {})  # type: ignore[union-attr]
            msg_type = raw.get("type", "")
            trace_id = raw.get("trace_id", "")
            gateway_room_id = getattr(room, "room_id", None)

            if msg_type == "gateway_query":
                question = raw.get("question", "")
                logger.info("manager_received_query", trace_id=trace_id, question=question[:80])

                # Classify intent → choose worker
                if _ANALYTICS_RE.search(question):
                    worker_type = "analytics-worker"
                else:
                    worker_type = "graph-worker"

                worker_user_id = f"@{worker_type}:{server_name}"

                # Ensure we have a DM room with this worker
                if worker_user_id not in _worker_rooms:
                    resp = await client.room_create(  # type: ignore[union-attr]
                        invite=[worker_user_id],
                        is_direct=True,
                    )
                    if not isinstance(resp, RoomCreateResponse):
                        logger.error("manager_worker_room_create_failed",
                                     worker=worker_user_id, error=str(resp))
                        return
                    _worker_rooms[worker_user_id] = resp.room_id
                    logger.info("manager_worker_room_created",
                                worker=worker_user_id, room_id=resp.room_id)
                    # Wait for worker to auto-join
                    await asyncio.sleep(2.0)

                worker_room_id = _worker_rooms[worker_user_id]
                _pending_tasks[trace_id] = gateway_room_id

                # Forward task to worker
                task_content = {
                    "type": "worker_task",
                    "trace_id": trace_id,
                    "question": question,
                    "user_id": raw.get("user_id", ""),
                    "org_id": raw.get("org_id", ""),
                    "roles": raw.get("roles", []),
                    "session_id": raw.get("session_id", ""),
                    "msgtype": "m.text",
                    "body": f"[HoneyBadge] worker_task trace={trace_id}",
                }
                await client.room_send(  # type: ignore[union-attr]
                    worker_room_id, "m.room.message", task_content
                )
                logger.info("manager_task_sent",
                            trace_id=trace_id, worker=worker_type, room_id=worker_room_id)

            elif msg_type in ("worker_result", "worker_error"):
                orig_gateway_room_id = _pending_tasks.pop(trace_id, None)
                if orig_gateway_room_id is None:
                    logger.warning("manager_unknown_trace", trace_id=trace_id, msg_type=msg_type)
                    return

                # Relay to gateway with simplified type ("result" / "error")
                relay_type = "result" if msg_type == "worker_result" else "error"
                relay_content = dict(raw)
                relay_content["type"] = relay_type
                relay_content["msgtype"] = "m.text"
                relay_content["body"] = f"[HoneyBadge] {relay_type} trace={trace_id}"

                await client.room_send(  # type: ignore[union-attr]
                    orig_gateway_room_id, "m.room.message", relay_content
                )
                logger.info("manager_relayed_result",
                            trace_id=trace_id, relay_type=relay_type,
                            gateway_room=orig_gateway_room_id)

        except Exception as exc:
            logger.error("manager_on_message_error", error=str(exc))

    client.add_event_callback(on_invite, InviteMemberEvent)
    client.add_event_callback(on_message, RoomMessage)

    resp = await client.login(password)
    if not isinstance(resp, LoginResponse):
        print(f"Manager Matrix login failed: {resp}", file=sys.stderr)
        sys.exit(1)

    logger.info("hiclaw_manager_started", user_id=user_id, homeserver=homeserver_url)

    try:
        await client.sync_forever(timeout=30000, full_state=True)
    finally:
        await client.close()


# =============================================================================
# HiClaw Worker — Matrix bot
# =============================================================================

async def _run_worker() -> None:
    """HiClaw Worker Matrix bot.

    Connects to the Matrix homeserver and listens for task messages from the
    Manager. Executes tasks by calling MCP Server tools over HTTP/SSE, then
    sends structured results back to the Manager room.

    Environment variables:
      WORKER_TYPE             graph-worker | analytics-worker
      MATRIX_HOMESERVER_URL   e.g. http://matrix:8008
      MATRIX_USER_ID          e.g. @graph-worker:matrix.local
      MATRIX_USER_PASSWORD    worker account password
      NEBULA_MCP_URL          e.g. http://honeybadge-nebula-mcp:8000
      AUDIT_MCP_URL           e.g. http://honeybadge-audit-mcp:8000
      CACHE_MCP_URL           e.g. http://honeybadge-cache-mcp:8000
    """
    import structlog
    logger = structlog.get_logger()

    try:
        from nio import AsyncClient, InviteMemberEvent, LoginResponse, RoomMessage
    except ImportError:
        print("ERROR: matrix-nio is not installed. Add it to requirements.txt.", file=sys.stderr)
        sys.exit(1)

    worker_type = os.environ.get("WORKER_TYPE", "graph-worker")
    homeserver_url = os.environ.get("MATRIX_HOMESERVER_URL", "http://localhost:8008")
    user_id = os.environ.get("MATRIX_USER_ID", f"@{worker_type}:matrix.local")
    password = os.environ.get("MATRIX_USER_PASSWORD", "")
    nebula_mcp_url = os.environ.get("NEBULA_MCP_URL", "http://localhost:8001")
    audit_mcp_url = os.environ.get("AUDIT_MCP_URL", "http://localhost:8002")
    cache_mcp_url = os.environ.get("CACHE_MCP_URL", "http://localhost:8003")

    client = AsyncClient(homeserver_url, user_id)

    async def on_invite(room: object, event: object) -> None:
        """Auto-accept invites from the Manager."""
        room_id = getattr(room, "room_id", None)
        if room_id:
            await client.join(room_id)  # type: ignore[union-attr]
            logger.info("worker_joined_room", worker=worker_type, room_id=room_id)

    async def on_message(room: object, event: object) -> None:
        """Handle task messages from the Manager."""
        sender = getattr(event, "sender", "")
        if sender == user_id:
            return

        try:
            raw = event.source.get("content", {})  # type: ignore[union-attr]
            msg_type = raw.get("type", "")
            trace_id = raw.get("trace_id", "")

            logger.info("worker_received_task",
                worker=worker_type,
                msg_type=msg_type,
                trace_id=trace_id,
            )

            if msg_type != "worker_task":
                return

            question = raw.get("question", "")
            task_user_id = raw.get("user_id", "")
            org_id = raw.get("org_id", "")
            roles = raw.get("roles", [])
            session_id = raw.get("session_id", "")
            manager_room_id = getattr(room, "room_id", None)
            start_ns = time.monotonic()

            try:
                # 1. Cache check
                cache_key = f"query:{abs(hash(question))}"
                cached = await _call_mcp_tool(
                    cache_mcp_url, "check_cache", {"key": cache_key}
                )
                if cached.get("hit"):
                    data = cached["data"]
                    logger.info("worker_cache_hit", trace_id=trace_id)
                    result_content = {
                        "type": "worker_result",
                        "trace_id": trace_id,
                        "summary": data.get("summary", ""),
                        "data": {
                            "ngql": data.get("ngql", ""),
                            "rows": data.get("rows", []),
                            "columns": data.get("columns", []),
                            "row_count": data.get("row_count", 0),
                            "execution_time_ms": data.get("execution_time_ms", 0),
                        },
                        "from_cache": True,
                        "msgtype": "m.text",
                        "body": f"[HoneyBadge] worker_result trace={trace_id} (cached)",
                    }
                    await client.room_send(  # type: ignore[union-attr]
                        manager_room_id, "m.room.message", result_content
                    )
                    return

                # 2. Generate nGQL
                gen = await _call_mcp_tool(
                    nebula_mcp_url, "generate_query", {"question": question}
                )
                ngql = gen.get("ngql", "").strip()
                if not ngql:
                    raise ValueError("LLM returned empty nGQL")
                logger.info("worker_ngql_generated", trace_id=trace_id, ngql=ngql[:120])

                # 3. Validate + Execute (L1-L3 + NebulaGraph)
                user_context = {
                    "user_id": task_user_id,
                    "org_id": str(org_id),
                    "roles": roles,
                }
                exec_r = await _call_mcp_tool(
                    nebula_mcp_url, "validate_and_execute",
                    {"ngql": ngql, "user_context": user_context},
                )
                if not exec_r.get("success"):
                    raise ValueError(
                        f"Validation/execution failed: {exec_r.get('details', [])}"
                    )
                rows = exec_r.get("rows", [])
                columns = exec_r.get("columns", [])
                row_count = exec_r.get("row_count", len(rows))
                exec_ms = exec_r.get("execution_time_ms", 0)
                logger.info("worker_query_executed",
                            trace_id=trace_id, row_count=row_count, exec_ms=exec_ms)

                # 4. Summarize results (L4 passthrough)
                summ = await _call_mcp_tool(
                    nebula_mcp_url, "summarize_query_results",
                    {"question": question, "columns": columns, "rows": rows, "ngql": ngql},
                )
                summary = summ.get("summary", "")

                elapsed_ms = int((time.monotonic() - start_ns) * 1000)

                # 5. Write audit log (L5)
                try:
                    await _call_mcp_tool(audit_mcp_url, "write_audit_log", {
                        "trace_id": trace_id,
                        "question": question,
                        "ngql": ngql,
                        "raw_result": {"rows": rows, "columns": columns},
                        "summary": summary,
                        "user_id": task_user_id,
                        "session_id": session_id,
                        "execution_time_ms": elapsed_ms,
                        "row_count": row_count,
                        "error_message": None,
                    })
                except Exception as audit_exc:
                    logger.error("worker_audit_write_failed",
                                 trace_id=trace_id, error=str(audit_exc))

                # 6. Cache the result
                try:
                    await _call_mcp_tool(cache_mcp_url, "cache_result", {
                        "key": cache_key,
                        "value": {
                            "ngql": ngql,
                            "rows": rows,
                            "columns": columns,
                            "row_count": row_count,
                            "execution_time_ms": exec_ms,
                            "summary": summary,
                        },
                        "ttl": 300,
                    })
                except Exception as cache_exc:
                    logger.warning("worker_cache_write_failed",
                                   trace_id=trace_id, error=str(cache_exc))

                # 7. Send worker_result to Manager room
                result_content = {
                    "type": "worker_result",
                    "trace_id": trace_id,
                    "summary": summary,
                    "data": {
                        "ngql": ngql,
                        "rows": rows,
                        "columns": columns,
                        "row_count": row_count,
                        "execution_time_ms": exec_ms,
                    },
                    "msgtype": "m.text",
                    "body": f"[HoneyBadge] worker_result trace={trace_id}",
                }
                await client.room_send(  # type: ignore[union-attr]
                    manager_room_id, "m.room.message", result_content
                )
                logger.info("worker_result_sent",
                            trace_id=trace_id, elapsed_ms=elapsed_ms)

            except Exception as exc:
                logger.error("worker_task_failed",
                             trace_id=trace_id, worker=worker_type, error=str(exc))

                # Best-effort error audit log
                try:
                    await _call_mcp_tool(audit_mcp_url, "write_audit_log", {
                        "trace_id": trace_id,
                        "question": question,
                        "ngql": "",
                        "raw_result": {},
                        "summary": "",
                        "user_id": task_user_id,
                        "session_id": session_id,
                        "execution_time_ms": int((time.monotonic() - start_ns) * 1000),
                        "row_count": 0,
                        "error_message": str(exc),
                    })
                except Exception:
                    pass

                # Send worker_error to Manager room
                error_content = {
                    "type": "worker_error",
                    "trace_id": trace_id,
                    "error_code": "WORKER_ERROR",
                    "error_message": str(exc),
                    "recoverable": False,
                    "msgtype": "m.text",
                    "body": f"[HoneyBadge] worker_error trace={trace_id}",
                }
                await client.room_send(  # type: ignore[union-attr]
                    manager_room_id, "m.room.message", error_content
                )

        except Exception as exc:
            logger.error("worker_on_message_error", worker=worker_type, error=str(exc))

    client.add_event_callback(on_invite, InviteMemberEvent)
    client.add_event_callback(on_message, RoomMessage)

    resp = await client.login(password)
    if not isinstance(resp, LoginResponse):
        print(f"Worker {worker_type} Matrix login failed: {resp}", file=sys.stderr)
        sys.exit(1)

    logger.info("hiclaw_worker_started", worker_type=worker_type, user_id=user_id)

    try:
        await client.sync_forever(timeout=30000, full_state=True)
    finally:
        await client.close()


if __name__ == "__main__":
    main()
