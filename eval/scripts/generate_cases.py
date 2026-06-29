# eval/scripts/generate_cases.py
"""Generate diverse eval cases using LLM based on schema + business rules.

Reads nebula-schema.ngql and the business concept mappings from
prompts/cypher_system.md, then asks the LLM to generate diverse questions
across the coverage matrix:
  5 user permissions x 4 difficulty levels x 3 business domains

Usage:
    py -3.12 -m eval.scripts.generate_cases --output eval/cases/generated/ --count 40
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from honeybadge.llm.adapter import LLMRequest, OpenAICompatibleAdapter

GENERATION_PROMPT = """你是 ERP 知识图谱测试用例生成器。请根据以下 Schema 和业务规则，生成多样化的测试问题。

# NebulaGraph Schema
{schema}

# 业务概念映射
{business_rules}

# 生成要求
请生成 {count} 个多样化的测试问题，覆盖以下维度：
- 用户权限: admin, analyst, procurement_lead, subsidiary_lead, auditor
- 难度: 单实体查询, 多跳遍历, 聚合统计, 风险检测
- 业务域: PTP(采购到付款), OTC(订单到收款), 主数据

每个问题输出 JSON:
{{
  "question": "问题文本",
  "user_context": "admin|analyst|procurement_lead|subsidiary_lead|auditor",
  "difficulty": "single_entity|multi_hop|aggregation|risk_detection",
  "domain": "PTP|OTC|master_data",
  "expected_tags": ["Tag1", "Tag2"],
  "key_concept": "简述这个问题在测试什么"
}}

输出 JSON 数组: [{{...}}, {{...}}]
"""


def _build_adapter() -> OpenAICompatibleAdapter:
    """Build LLM adapter from env vars (same pattern as eval/runner.py)."""
    config = {
        "endpoint": os.environ.get("LLM_ENDPOINT", "http://localhost:8080"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "model": os.environ.get("LLM_MODEL", "glm-4-flash"),
        "timeout": 300,
    }
    return OpenAICompatibleAdapter(config, None)


def _extract_business_rules() -> str:
    """Extract the business concept -> nGQL mapping section from cypher_system.md."""
    repo_root = Path(__file__).resolve().parents[2]
    prompt_path = repo_root / "src" / "honeybadge" / "llm" / "prompts" / "cypher_system.md"
    if not prompt_path.exists():
        return ""
    prompt = prompt_path.read_text(encoding="utf-8")
    # Extract the "业务概念 -> nGQL 查询映射" section
    m = re.search(r"# 业务概念.*?(?=\n# |\Z)", prompt, re.DOTALL)
    return m.group(0) if m else prompt[:2000]


def _load_schema() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    parts: list[str] = []
    for name in ("nebula-schema.ngql", "nebula-edges.ngql"):
        p = repo_root / "deploy" / "docker" / name
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


async def generate_cases(count: int = 40) -> list[dict]:
    """Use LLM to generate diverse eval case questions."""
    adapter = _build_adapter()

    prompt = GENERATION_PROMPT.format(
        schema=_load_schema()[:4000],  # Truncate to fit context
        business_rules=_extract_business_rules()[:3000],
        count=count,
    )

    request = LLMRequest(
        messages=[
            {"role": "system", "content": "你是测试用例生成器，输出必须是合法 JSON 数组。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,  # Higher temperature for diversity
        max_tokens=8192,
    )

    resp = await adapter.chat(request)
    # Parse JSON array from response
    text = resp.content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Log the raw response for debugging
        print(f"ERROR: LLM returned invalid JSON: {e}")
        print(f"Raw response (first 500 chars): {text[:500]}")
        raise ValueError(
            f"LLM returned invalid JSON: {e}. "
            f"Raw response starts with: {text[:200]}"
        ) from e


def _to_yaml(case: dict, idx: int) -> str:
    """Convert a generated case dict to a YAML skeleton."""
    case_id = f"GEN-{case.get('domain', 'UNK')}-{idx:03d}"
    tags = case.get("expected_tags", [])
    tags_yaml = ", ".join(tags) if tags else ""
    tags_block = (
        f"    - type: expected_tags\n      tags: [{tags_yaml}]\n" if tags_yaml else ""
    )
    question_line = f"question: {json.dumps(case['question'], ensure_ascii=False)}"
    return f"""id: {case_id}
category: ngql_accuracy
subcategory: {case.get('difficulty', 'unknown')}
{question_line}
user_context: {case.get('user_context', 'admin')}

# TODO: review and fill in golden_ngql
ci:
  golden_ngql: |
    # TODO: write correct nGQL
  checks:
    - type: syntax_valid
    - type: forbidden_ops_absent
      ops: [GO, FETCH, "FIND PATH", "GET SUBGRAPH"]
    - type: has_limit
{tags_block}
# TODO: review rubric
offline:
  judge:
    rubric: |
      测试点: {case.get('key_concept', 'TODO')}
    pass_criteria: 4
    runs: 3
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate eval cases with LLM")
    parser.add_argument("--output", default="eval/cases/generated", help="Output directory")
    parser.add_argument("--count", type=int, default=40, help="Number of cases to generate")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.count} eval cases with LLM...")
    cases = asyncio.run(generate_cases(args.count))
    print(f"Generated {len(cases)} cases")

    for i, case in enumerate(cases):
        yaml = _to_yaml(case, i + 1)
        out_file = output_dir / f"gen-{i + 1:03d}.yaml"
        out_file.write_text(yaml, encoding="utf-8")
        print(f"  {case.get('question', '?')[:50]}...")

    print(f"\nWrote {len(cases)} case skeletons to {output_dir}")
    print("Next: review each file, fill in golden_ngql and rubric")


if __name__ == "__main__":
    main()
