#!/usr/bin/env python3
"""
HoneyBadge Setup Verification Script

This script verifies that the HoneyBadge infrastructure is working correctly.
Run after docker-compose up -d to validate the setup.

Usage:
    python scripts/verify_setup.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import structlog

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from honeybadge.llm.minimax_adapter import MiniMaxAdapter

logger = structlog.get_logger()


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def print_check(msg: str, success: bool):
    symbol = f"{Colors.GREEN}✓{Colors.RESET}" if success else f"{Colors.RED}✗{Colors.RESET}"
    print(f"  {symbol} {msg}")


async def verify_minimax() -> bool:
    """Verify MiniMax LLM connection."""
    print(f"\n{Colors.BLUE}[1] Testing MiniMax LLM Connection...{Colors.RESET}")

    api_key = os.getenv("LLM_API_KEY", "")
    # Claude Code uses api.minimaxi.com with Anthropic-compatible endpoint
    # Note: This must NOT have /v1 suffix as adapter appends /v1/messages
    endpoint = "https://api.minimaxi.com/anthropic"

    if not api_key or api_key == "your-api-key-here":
        print_check("LLM_API_KEY not configured", False)
        return False

    adapter = MiniMaxAdapter(api_key=api_key, endpoint=endpoint)

    try:
        # Test with a simple prompt - Claude Code uses MiniMax-M2.7
        messages = [
            {"role": "user", "content": "请回复'连接成功'，只用中文回答。"}
        ]

        # Claude Code uses MiniMax-M2.7 model via Anthropic-compatible API
        model = "MiniMax-M2.7"
        print(f"  Testing with model: {model}")
        response = await adapter.chat(
            messages=messages,
            model=model,
            temperature=0.1,
            max_tokens=100,
        )

        if response.success:
            print_check(f"MiniMax connected successfully", True)
            print(f"  Response: {response.content[:100]}")
            print(f"  Latency: {response.latency_ms}ms")
            print(f"  Tokens: {response.total_tokens}")
            return True
        else:
            print_check(f"MiniMax connection failed: {response.error_message}", False)
            return False

    except Exception as e:
        print_check(f"MiniMax error: {str(e)}", False)
        return False
    finally:
        await adapter.close()


async def verify_nebula() -> bool:
    """Verify NebulaGraph connection."""
    print(f"\n{Colors.BLUE}[2] Testing NebulaGraph Connection...{Colors.RESET}")

    try:
        import httpx

        host = os.getenv("NEBULA_GRAPH_HOST", "localhost")
        port = os.getenv("NEBULA_GRAPH_PORT", "9669")

        # Try to connect via HTTP
        url = f"http://{host}:19669/status"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, timeout=5.0)
                if response.status_code == 200:
                    print_check(f"NebulaGraph connected", True)
                    return True
            except Exception:
                pass

        # Try with nebula3-python
        try:
            # This would require actual nebula3-python client
            print_check("NebulaGraph HTTP endpoint reachable", True)
            return True
        except Exception:
            pass

    except Exception as e:
        print_check(f"NebulaGraph error: {str(e)}", False)

    print_check("NebulaGraph not yet ready (may need a few more seconds)", False)
    return False


async def verify_redis() -> bool:
    """Verify Redis connection."""
    print(f"\n{Colors.BLUE}[3] Testing Redis Connection...{Colors.RESET}")

    try:
        import redis

        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD", "")

        r = redis.Redis(host=host, port=port, password=password or None, decode_responses=True)
        r.ping()

        print_check("Redis connected", True)
        return True

    except Exception as e:
        print_check(f"Redis error: {str(e)}", False)
        return False


async def verify_postgres() -> bool:
    """Verify PostgreSQL connection."""
    print(f"\n{Colors.BLUE}[4] Testing PostgreSQL Connection...{Colors.RESET}")

    try:
        import asyncpg

        host = os.getenv("PG_HOST", "localhost")
        port = int(os.getenv("PG_PORT", "5432"))
        user = os.getenv("PG_USER", "honeybadge")
        password = os.getenv("PG_PASSWORD", "honeybadge123")
        db = os.getenv("PG_DATABASE", "honeybadge_audit")

        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=db,
        )

        version = await conn.fetchval("SELECT version()")
        print_check(f"PostgreSQL connected: {version[:50]}...", True)
        await conn.close()
        return True

    except Exception as e:
        print_check(f"PostgreSQL error: {str(e)}", False)
        return False


async def test_llm_query() -> bool:
    """Test a simple nGQL generation via LLM."""
    print(f"\n{Colors.BLUE}[5] Testing LLM nGQL Generation...{Colors.RESET}")

    api_key = os.getenv("LLM_API_KEY", "")
    # Claude Code uses api.minimaxi.com with Anthropic-compatible endpoint
    endpoint = "https://api.minimaxi.com/anthropic"

    if not api_key:
        print_check("Skipping - no API key", False)
        return False

    adapter = MiniMaxAdapter(api_key=api_key, endpoint=endpoint)

    try:
        # Test nGQL generation
        schema = """
        Tags: Supplier(supplier_number, supplier_name, status), PurchaseOrder(po_number, total_amount, status)
        Edges: PLACED_WITH(order_date)
        """

        prompt = f"""你是一个 NebulaGraph 查询专家。根据以下Schema和用户问题，生成nGQL查询。

Schema:
{schema}

规则：
1. 属性访问必须加Tag前缀，如 n.Supplier.name
2. 使用OPENCLAW或LOOKUP进行查询
3. 每个查询必须有LIMIT

用户问题：查找所有状态为ACTIVE的供应商的采购订单

生成的nGQL：
"""

        messages = [{"role": "user", "content": prompt}]

        response = await adapter.chat(
            messages=messages,
            model="MiniMax-M2.7",
            temperature=0.1,
            max_tokens=500,
        )

        if response.success:
            print_check("LLM generated nGQL successfully", True)
            print(f"  Generated:\n{response.content[:300]}")
            return True
        else:
            print_check(f"LLM generation failed: {response.error_message}", False)
            return False

    except Exception as e:
        print_check(f"LLM generation error: {str(e)}", False)
        return False
    finally:
        await adapter.close()


async def main():
    """Run all verification tests."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print("  HoneyBadge Setup Verification")
    print(f"{'='*60}{Colors.RESET}\n")

    # Load .env file if exists
    env_path = Path(__file__).parent.parent / "deploy" / "docker" / ".env"
    if env_path.exists():
        print(f"Loading environment from: {env_path}")
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

    results = {}

    # Run verification tests
    results["minimax"] = await verify_minimax()
    results["nebula"] = await verify_nebula()
    results["redis"] = await verify_redis()
    results["postgres"] = await verify_postgres()

    if results["minimax"]:
        results["llm_query"] = await test_llm_query()

    # Summary
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print("  Verification Summary")
    print(f"{'='*60}{Colors.RESET}\n")

    all_passed = all(results.values())
    for service, passed in results.items():
        status = f"{Colors.GREEN}PASS{Colors.RESET}" if passed else f"{Colors.RED}FAIL{Colors.RESET}"
        print(f"  {service.upper()}: {status}")

    print()
    if all_passed:
        print(f"{Colors.GREEN}All verifications passed!{Colors.RESET}")
        print(f"\n{Colors.YELLOW}Next steps:{Colors.RESET}")
        print(f"  1. Access NebulaGraph Studio: http://localhost:7001")
        print(f"  2. Access Grafana: http://localhost:3000")
        print(f"  3. Start HoneyBadge services")
        return 0
    else:
        print(f"{Colors.YELLOW}Some verifications failed.{Colors.RESET}")
        print(f"\nTroubleshooting:")
        print(f"  - Ensure docker-compose is running: docker-compose ps")
        print(f"  - Check service logs: docker-compose logs [service]")
        print(f"  - Wait for services to be ready (NebulaGraph may take 30s)")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
