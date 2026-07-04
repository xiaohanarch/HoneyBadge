"""TDD tests for multi-turn conversation context pipeline.

Covers:
  - Matrix DM history extraction (fetch-conversation-history.py)
  - adapter.generate_ngql conversation_history injection
"""
import importlib.util
import json
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from honeybadge.llm.adapter import LLMRequest, LLMResponse, generate_ngql

# ---------------------------------------------------------------------------
# Load fetch-conversation-history.py as a module (it's a script, not a package).
# ---------------------------------------------------------------------------
_HIST_SCRIPT = pathlib.Path(
    "hiclaw/manager/agent/skills/fast-query/fetch-conversation-history.py"
)


def _load_history_module():
    spec = importlib.util.spec_from_file_location("fetch_conversation_history", _HIST_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_hist = _load_history_module()
_extract_qa_pairs = _hist._extract_qa_pairs
_truncate = _hist._truncate
CHAR_BUDGET = _hist.CHAR_BUDGET


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
USER_MXID = "@hb-admin:matrix-local.hiclaw.io"
MGR_MXID = "@manager:matrix-local.hiclaw.io"


def _user_event(text: str, ts: int = 0) -> dict:
    return {
        "type": "m.room.message",
        "sender": USER_MXID,
        "origin_server_ts": ts,
        "content": {"msgtype": "m.text", "body": text},
    }


def _assistant_event(summary: str, cypher: str, ts: int = 0) -> dict:
    """Manager reply carrying a contract 002 x-honeybadge payload."""
    return {
        "type": "m.room.message",
        "sender": MGR_MXID,
        "origin_server_ts": ts,
        "content": {
            "msgtype": "m.text",
            "body": summary,
            "x-honeybadge": {
                "v": "1",
                "contract": "002",
                "trace_id": "TRC-x",
                "payload": {
                    "summary": summary,
                    "cypher": cypher,
                    "raw_data": [],
                    "columns": [],
                    "execution_time_ms": 5,
                    "row_count": 1,
                },
            },
        },
    }


def _membership_event(ts: int = 0) -> dict:
    """A join/leave event that must be filtered out."""
    return {
        "type": "m.room.member",
        "sender": USER_MXID,
        "origin_server_ts": ts,
        "content": {"membership": "join"},
    }


def _heartbeat_event(ts: int = 0) -> dict:
    """A notice/heartbeat message that must be filtered out."""
    return {
        "type": "m.room.message",
        "sender": MGR_MXID,
        "origin_server_ts": ts,
        "content": {"msgtype": "m.notice", "body": "heartbeat"},
    }


# ---------------------------------------------------------------------------
# Tests: Matrix Q&A pairing
# ---------------------------------------------------------------------------
class TestExtractQaPairs:
    def test_extract_qa_pairs_basic(self):
        """A clean user→assistant→user→assistant timeline pairs correctly."""
        events = [
            _user_event("查询采购订单", ts=1),
            _assistant_event("找到5个采购订单", "MATCH (p:PurchaseOrder) RETURN p", ts=2),
            _user_event("统计这些订单的总金额", ts=3),
            _assistant_event("总金额 12345", "MATCH (p:PurchaseOrder) RETURN sum(p.amount)", ts=4),
        ]
        pairs = _extract_qa_pairs(events, USER_MXID)
        assert len(pairs) == 4  # 2 Q&A turns × 2 messages
        assert pairs[0] == {"role": "user", "content": "查询采购订单"}
        assert "上一轮 nGQL: MATCH (p:PurchaseOrder) RETURN p" in pairs[1]["content"]
        assert "结果摘要: 找到5个采购订单" in pairs[1]["content"]
        assert pairs[2] == {"role": "user", "content": "统计这些订单的总金额"}
        assert "sum(p.amount)" in pairs[3]["content"]

    def test_extract_qa_pairs_filters_non_message_events(self):
        """join/leave/heartbeat/notice events are ignored; only Q&A pairs remain."""
        events = [
            _membership_event(ts=0),
            _heartbeat_event(ts=1),
            _user_event("查询供应商", ts=2),
            _membership_event(ts=3),  # stray member event between Q and A
            _assistant_event("找到供应商", "MATCH (s:Supplier) RETURN s", ts=4),
            _heartbeat_event(ts=5),
        ]
        pairs = _extract_qa_pairs(events, USER_MXID)
        assert len(pairs) == 2  # exactly one Q&A pair
        assert pairs[0]["role"] == "user"
        assert pairs[0]["content"] == "查询供应商"
        assert pairs[1]["role"] == "assistant"

    def test_extract_qa_pairs_truncates_to_max_rounds(self):
        """10 Q&A turns → only the last 3 retained after _truncate(max_rounds=3)."""
        events = []
        for i in range(10):
            events.append(_user_event(f"问题{i}", ts=i * 2))
            events.append(_assistant_event(
                f"回答{i}", f"MATCH (n) RETURN n  -- {i}", ts=i * 2 + 1,
            ))
        pairs = _extract_qa_pairs(events, USER_MXID)
        assert len(pairs) == 20  # all 10 turns extracted
        truncated = _truncate(pairs, max_rounds=3)
        assert len(truncated) == 6  # 3 turns × 2 messages
        # Should be the LAST 3 turns (问题7,8,9)
        assert truncated[0]["content"] == "问题7"
        assert truncated[4]["content"] == "问题9"

    def test_extract_qa_pairs_char_budget_reduces_rounds(self):
        """When history exceeds CHAR_BUDGET, _truncate drops rounds until under budget."""
        # Build 3 rounds whose total exceeds CHAR_BUDGET.
        big = "x" * (CHAR_BUDGET // 2 + 100)  # each assistant msg ~half budget
        pairs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": big},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": big},
            {"role": "user", "content": "q3"},
            {"role": "assistant", "content": big},
        ]
        # 3 rounds × big → over budget → must shrink to 2, then 1.
        result = _truncate(pairs, max_rounds=3)
        total = sum(len(m["content"]) for m in result)
        assert total <= CHAR_BUDGET
        # With big ~half budget, only 1 round fits → 2 messages.
        assert len(result) == 2
        # The most recent round is retained.
        assert result[0]["content"] == "q3"

    def test_extract_qa_pairs_graceful_degradation(self):
        """main() outputs [] on any error (API unreachable, missing config, etc.)."""
        import io
        from contextlib import redirect_stdout

        argv_backup = sys.argv
        buf = io.StringIO()
        with patch.object(_hist, "_load_manager_token", side_effect=RuntimeError("no token")):
            sys.argv = ["fetch-conversation-history.py", "--user-id", "admin"]
            try:
                with redirect_stdout(buf):
                    rc = _hist.main()
            finally:
                sys.argv = argv_backup
        assert rc == 0
        assert json.loads(buf.getvalue()) == []


# ---------------------------------------------------------------------------
# Tests: adapter.generate_ngql conversation_history injection
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestAdapterHistoryInjection:
    """Verify generate_ngql splices conversation_history into messages correctly."""

    async def _run_generate_ngql(self, conversation_history=None, user_context=None):
        """Run generate_ngql with a fake adapter that captures the request."""
        captured: dict = {}

        async def fake_chat(request: LLMRequest) -> LLMResponse:
            captured["messages"] = request.messages
            return LLMResponse(
                content="MATCH (n) RETURN n",
                model="fake",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                finish_reason="stop",
                latency_ms=1,
            )

        adapter = MagicMock()
        adapter.chat = fake_chat

        await generate_ngql(
            adapter=adapter,
            question="统计这些订单的总金额",
            schema_info="SCHEMA",
            ontology_info="ONTOLOGY",
            user_context=user_context,
            trace_id="TRC-test",
            conversation_history=conversation_history,
        )
        return captured["messages"]

    async def test_adapter_injects_history(self):
        """conversation_history is spliced between system prompt and current question."""
        history = [
            {"role": "user", "content": "查询采购订单"},
            {"role": "assistant", "content": "上一轮 nGQL: MATCH (p:PurchaseOrder) RETURN p\n结果摘要: 5个订单"},
        ]
        messages = await self._run_generate_ngql(conversation_history=history)

        assert messages[0]["role"] == "system"
        # History must appear AFTER system, BEFORE current question.
        assert messages[1] == history[0]
        assert messages[2] == history[1]
        # Current question is last.
        assert messages[-1]["role"] == "user"
        assert "统计这些订单的总金额" in messages[-1]["content"]
        # Total: system + 2 history + 1 current = 4.
        assert len(messages) == 4

    async def test_adapter_no_history_no_change(self):
        """conversation_history=None → messages layout identical to single-turn (2 messages)."""
        messages = await self._run_generate_ngql(conversation_history=None)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "统计这些订单的总金额"

    async def test_adapter_user_context_still_works(self):
        """With history present, user_context still injects into the last (current) message."""
        history = [
            {"role": "user", "content": "查询采购订单"},
            {"role": "assistant", "content": "上一轮 nGQL: MATCH (p) RETURN p\n结果摘要: ok"},
        ]
        user_context = {"user_id": "admin", "org_ids": [1], "data_scope": "ORG"}
        messages = await self._run_generate_ngql(
            conversation_history=history,
            user_context=user_context,
        )
        # The last message (current question) must carry the permission context.
        last = messages[-1]
        assert last["role"] == "user"
        assert "admin" in last["content"]
        assert "org_ids" in last["content"]
        assert "统计这些订单的总金额" in last["content"]
        # History messages must NOT be modified by user_context injection.
        assert messages[1]["content"] == "查询采购订单"
        assert "org_ids" not in messages[2]["content"]
