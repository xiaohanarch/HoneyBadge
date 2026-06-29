# eval/scorers/llm_judge.py
"""LLM-as-judge scorer — uses a stronger model to evaluate nGQL semantic quality."""
from __future__ import annotations

import json
import re
from typing import Any

from honeybadge.llm.adapter import LLMAdapter, LLMRequest


_JUDGE_SYSTEM_PROMPT = """你是 nGQL 查询评审专家。你需要根据评分标准对生成的 nGQL 查询打分（1-5 分）。

评分规则：
5分 = 完全正确，语义准确，语法规范
4分 = 基本正确，有小瑕疵但不影响结果
3分 = 部分正确，有语义偏差但方向对
2分 = 大部分错误，但有一些正确元素
1分 = 完全错误，答非所问

请输出 JSON 格式：{"score": 1-5, "reason": "简要说明"}"""


class LLMJudge:
    """LLM-as-judge: evaluates generated nGQL using a stronger model."""

    def __init__(self, judge_adapter: LLMAdapter) -> None:
        self.adapter = judge_adapter

    async def evaluate(
        self,
        question: str,
        generated_ngql: str,
        rubric: str,
    ) -> tuple[int, str]:
        """Score the generated nGQL. Returns (score 1-5, reason)."""
        user_prompt = f"""# 用户问题
{question}

# 生成的 nGQL
{generated_ngql}

# 评分标准
{rubric}

请按评分标准打分，输出 JSON：{{"score": 1-5, "reason": "..."}}
"""
        request = LLMRequest(
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        resp = await self.adapter.chat(request)
        return parse_judge_response(resp.content)


def parse_judge_response(raw: str) -> tuple[int, str]:
    """Parse the judge's JSON response. Returns (score, reason)."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        score = int(data.get("score", 0))
        reason = str(data.get("reason", ""))
        if score < 1 or score > 5:
            return 0, f"Score out of range: {score}"
        return score, reason
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return 0, f"Failed to parse judge response: {e}"
