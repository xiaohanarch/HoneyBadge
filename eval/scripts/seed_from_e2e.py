# eval/scripts/seed_from_e2e.py
"""Extract seed eval cases from existing E2E test files.

Parses tests/e2e/test_*.py for send_chat_query() / send_query_on_page() calls,
extracts the question text, and generates YAML case skeletons for human review.

Usage:
    py -3.12 -m eval.scripts.seed_from_e2e --output eval/cases/seeded/
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

# Map E2E test files to eval categories
E2E_TO_CATEGORY = {
    "test_02_chat": "ngql_accuracy",
    "test_05_permissions": "antihal_permission",
    "test_06_antihal": "antihal_permission",
    "test_04_isolation": "antihal_permission",
}

# Two patterns: send_chat_query("question") and send_query_on_page(page, "question")
QUESTION_RE_FIRST = re.compile(r'send_chat_query\s*\(\s*"([^"]+)"')
QUESTION_RE_SECOND = re.compile(r'send_query_on_page\s*\([^,]+,\s*"([^"]+)"')


def extract_questions(e2e_dir: Path) -> list[tuple[str, str, str]]:
    """Extract (question, source_file, category) from E2E test files."""
    results: list[tuple[str, str, str]] = []
    for test_file in sorted(e2e_dir.glob("test_*.py")):
        stem = test_file.stem  # e.g., test_02_chat
        category = "ngql_accuracy"
        for prefix, cat in E2E_TO_CATEGORY.items():
            if stem.startswith(prefix):
                category = cat
                break
        content = test_file.read_text(encoding="utf-8")
        # Match both patterns
        for m in QUESTION_RE_FIRST.finditer(content):
            question = m.group(1).strip()
            if question:
                results.append((question, stem, category))
        for m in QUESTION_RE_SECOND.finditer(content):
            question = m.group(1).strip()
            if question:
                results.append((question, stem, category))
    return results


def generate_yaml_skeleton(
    case_id: str,
    question: str,
    category: str,
    source: str,
) -> str:
    """Generate a YAML case skeleton for human review."""
    return f"""id: {case_id}
category: {category}
subcategory: from_e2e_{source}
question: "{question}"
user_context: admin  # TODO: review — set to analyst/procurement_lead/etc. as appropriate

# TODO: fill in golden_ngql (write the correct nGQL for this question)
ci:
  golden_ngql: |
    # TODO: write correct nGQL here
  checks:
    - type: syntax_valid
    - type: forbidden_ops_absent
      ops: [GO, FETCH, "FIND PATH", "GET SUBGRAPH"]
    - type: has_limit

# TODO: fill in rubric (what makes a correct answer for this question?)
offline:
  judge:
    rubric: |
      # TODO: write rubric here
    pass_criteria: 4
    runs: 3
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed eval cases from E2E tests")
    parser.add_argument("--e2e-dir", default="tests/e2e", help="E2E test directory")
    parser.add_argument("--output", default="eval/cases/seeded", help="Output directory")
    args = parser.parse_args()

    e2e_dir = Path(args.e2e_dir)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    questions = extract_questions(e2e_dir)
    print(f"Extracted {len(questions)} questions from E2E tests")

    seen: set[str] = set()
    count = 0
    for question, source, category in questions:
        # Deduplicate by question text
        key = question.lower()
        if key in seen:
            continue
        seen.add(key)

        case_id = f"SEED-{category[:4].upper()}-{count + 1:03d}"
        yaml = generate_yaml_skeleton(case_id, question, category, source)
        out_file = output_dir / f"{case_id.lower()}.yaml"
        out_file.write_text(yaml, encoding="utf-8")
        print(f"  {case_id}: {question[:50]}...")
        count += 1

    print(f"\nWrote {count} case skeletons to {output_dir}")
    print("Next: review each file, fill in golden_ngql and rubric, then move to cases/<category>/")


if __name__ == "__main__":
    main()
