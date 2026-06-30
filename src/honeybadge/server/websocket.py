"""WebSocket query handler for HoneyBadge server.

Receives QueryRequest messages, processes them through the LLM+NebulaGraph pipeline,
and returns QueryResponse messages with trace_id and execution_time_ms.
"""

import re
import time
from pathlib import Path
from typing import Any

import structlog

from honeybadge.core.trace import generate_trace_id
from honeybadge.db.nebula import NebulaGraphClient
from honeybadge.db.postgres import PostgreSQLClient
from honeybadge.llm.adapter import OpenAICompatibleAdapter
from honeybadge.llm.adapter import generate_ngql as llm_generate_ngql
from honeybadge.llm.adapter import summarize_results as llm_summarize_results
from honeybadge.permission_service.config import PERMISSION_CONFIG
from honeybadge.permission_service.permission_enforcer import PermissionEnforcer

_permission_enforcer = PermissionEnforcer()

logger = structlog.get_logger()

# Known entity keywords for schema filtering (English + Chinese)
_ENTITY_KEYWORDS = {
    # Vertex types
    "supplier": ["supplier", "供应商", "供货商"],
    "invoice": ["invoice", "发票", "应付发票"],
    "payment": ["payment", "付款", "付款记录", "付款单", "交易", "付款操作", "付款行为"],
    "purchase_order": ["purchaseorder", "po", "采购订单", "订单", "采购单"],
    "receipt": ["receipt", "收货", "入库", "送货单"],
    "item": ["item", "物料", "商品", "货品", "物料"],
    "employee": ["employee", "员工", "雇员", "采购员", "员工"],
    "organization": ["organization", "org", "组织", "部门", "公司", "事业部"],
    "currency": ["currency", "货币", "币种", "汇率"],
    "uom": ["uom", "计量单位", "单位"],
    "gl_journal": ["gljournal", "gl_journal", "gljournalentry", "日记账", "分录", "凭证"],
    "bom": ["bom", "物料清单", "配方"],
    "contract": ["contract", "合同"],
    "sales_order": ["salesorder", "so", "销售订单", "SalesOrder"],
    "shipment": ["shipment", "出货", "发货", "送货"],
    "ar_invoice": ["arinvoice", "ar_invoice", "应收发票", "ARInvoice"],
    "ar_receipt": ["arreceipt", "ar_receipt", "应收收款", "ARReceipt"],
    "qualification": ["qualification", "资质", "认证", "证书", "SupplierQualification"],
    "approval": ["approval", "approvalrecord", "审批", "审核", "ApprovalRecord"],
    # Edge types
    "placed_with": ["placed_with", "下达给", "订单给"],
    "has_receipt": ["has_receipt", "收货"],
    "has_invoice": ["has_invoice", "发票"],
    "pays_invoice": ["pays_invoice", "付款发票", "支付发票"],
    "paid_to": ["paid_to", "付款给", "支付给"],
    "invoiced_by": ["invoiced_by", "发票开具方", "开票方"],
    "supplies_item": ["supplies_item", "供应物料", "供货"],
    "has_qualification": ["has_qualification", "持有资质", "资质"],
    "ordered_by": ["ordered_by", "订购", "下单"],
    "belongs_to_org": ["belongs_to_org", "属于组织", "属于"],
    "ships_from": ["ships_from", "发货", "出货"],
    "sold_to": ["sold_to", "售达", "客户"],
    "contains_payment": ["contains_payment", "包含付款"],
    "accounting_for": ["accounting_for", "会计分录", "记账"],
    "applies_to": ["applies_to", "应用于", "application"],
    "approved_by": ["approved_by", "审批人", "审批"],
    "distributed_to": ["distributed_to", "分配"],
    # Business concepts
    "risk": ["风险", "高风险", "risky", "fraud", "fake", "虚假", "欺诈", "可疑", "异常", "问题", "诈骗"],
    "match": ["三单", "三单匹配", "匹配", "对账", "核销"],
    "overdue": ["超期", "逾期", "到期", "账龄"],
    "blocked": ["冻结", "blocked", "停用", "黑名单", "无效"],
    "active": ["active", "正常", "启用", "活跃"],
    "credit": ["信用", "credit", "评级", "信用评级"],
    "amount": ["金额", "amount", "数额", "总额", "数量"],
    "status": ["状态", "status", "状况"],
}

# Ontology files and their related entity keys
_ONTOLOGY_FILES = {
    "supplier.md": {"supplier", "qualification", "placed_with", "has_qualification", "supplies_item", "blocked", "credit", "active", "risk"},
    "payable.md": {"payment", "invoice", "pays_invoice", "paid_to", "invoiced_by", "has_invoice", "contains_payment", "overdue", "status", "amount"},
    "procurement.md": {"purchase_order", "receipt", "item", "ordered_by", "has_receipt", "belongs_to_org", "amount", "status"},
    "receivable.md": {"sales_order", "shipment", "ar_invoice", "ar_receipt", "sold_to", "ships_from"},
    "constraints.md": {"risk", "match", "overdue", "blocked", "amount", "status"},
    "master-data.md": {"organization", "currency", "uom", "employee", "contract", "gl_journal"},
}


def _strip_markdown_fence(text: str) -> str:
    """Extract nGQL from LLM output, stripping thinking tags, fences, and prose."""
    text = text.strip()
    # Remove <think>...</think> blocks (MiniMax-M2.7 reasoning output)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.strip()

    # Try to extract from code fence first (most reliable)
    fence_match = re.search(r"```\w*\s*\n?(.*?)```", text, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # No code fence — extract starting from first nGQL keyword
    ngql_match = re.search(
        r"^((?:MATCH|LOOKUP|GO|FETCH|FIND|USE|SHOW|DESCRIBE)\b.*)$",
        text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if ngql_match:
        return ngql_match.group(1).strip().rstrip(";")

    # Fallback: return as-is (original behavior)
    return text.strip()

# Path to prompts directory (resolved relative to src/honeybadge/)
_PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"

# In-memory schema cache
_schema_cache: dict[str, str] = {}


def _extract_keywords(question: str) -> set[str]:
    """Extract entity and concept keywords from a Chinese/English question.

    Returns a set of lowercase keyword strings found in the question.
    """
    # Normalize: lowercase and remove spaces for matching
    # "purchase order" -> "purchaseorder", "purchase_order" still matches
    normalized = question.lower()
    normalized_nospace = re.sub(r"\s+", "", normalized)
    found: set[str] = set()

    for key, aliases in _ENTITY_KEYWORDS.items():
        for alias in aliases:
            alias_lower = alias.lower()
            # Check both with spaces (for Chinese) and without spaces (for English phrases)
            if alias_lower in normalized or alias_lower in normalized_nospace:
                found.add(key)
                break

    # If no keywords found, default to all (empty prompt would be worse)
    return found


def _is_relevant(keywords: set[str], text: str) -> bool:
    """Check if text is relevant to any of the given keywords."""
    if not keywords:
        return True
    text_lower = text.lower()
    for kw in keywords:
        aliases = _ENTITY_KEYWORDS.get(kw, [kw])
        for alias in aliases:
            if alias.lower() in text_lower:
                return True
    return False


async def get_filtered_schema_str(
    nebula: NebulaGraphClient,
    keywords: set[str],
    space: str = "honeybadge",
) -> str:
    """Get filtered NebulaGraph schema containing only keyword-relevant tags and edges.

    Falls back to full schema if cache miss.
    """
    # Try cache first (unfiltered full schema)
    full_schema = _schema_cache.get(space)
    if full_schema is None:
        # Build full schema and cache it
        lines = [f"# Schema for space: {space}\n"]

        tags_result = await nebula.execute("SHOW TAGS", space=space)
        tag_names = []
        if tags_result.success:
            for row in tags_result.rows:
                name = row.get("Name") or row.get("name") or ""
                if name:
                    tag_names.append(str(name))

        lines.append("## Tags")
        for tag in tag_names:
            desc_result = await nebula.execute(f"DESCRIBE TAG `{tag}`", space=space)
            if desc_result.success:
                lines.append(f"### {tag}")
                for row in desc_result.rows:
                    col = row.get("Field") or row.get("field") or ""
                    typ = row.get("Type") or row.get("type") or ""
                    null = row.get("Null") or row.get("null") or ""
                    default = row.get("Default") or row.get("default") or ""
                    extra = row.get("Extra") or row.get("extra") or ""
                    props_str = f"{typ}"
                    if null == "NO":
                        props_str += " NOT NULL"
                    if default:
                        props_str += f" DEFAULT {default}"
                    if extra:
                        props_str += f" {extra}"
                    lines.append(f"  - {col}: {props_str}")

        edges_result = await nebula.execute("SHOW EDGES", space=space)
        edge_names = []
        if edges_result.success:
            for row in edges_result.rows:
                name = row.get("Name") or row.get("name") or ""
                if name:
                    edge_names.append(str(name))

        lines.append("\n## Edges")
        for edge in edge_names:
            desc_result = await nebula.execute(f"DESCRIBE EDGE `{edge}`", space=space)
            if desc_result.success:
                lines.append(f"### {edge}")
                for row in desc_result.rows:
                    col = row.get("Field") or row.get("field") or ""
                    typ = row.get("Type") or row.get("type") or ""
                    null = row.get("Null") or row.get("null") or ""
                    default = row.get("Default") or row.get("default") or ""
                    extra = row.get("Extra") or row.get("extra") or ""
                    props_str = f"{typ}"
                    if null == "NO":
                        props_str += " NOT NULL"
                    if default:
                        props_str += f" DEFAULT {default}"
                    if extra:
                        props_str += f" {extra}"
                    lines.append(f"  - {col}: {props_str}")

        full_schema = "\n".join(lines)
        _schema_cache[space] = full_schema

    # No filtering needed
    if not keywords:
        return full_schema

    # Filter to only relevant sections
    # Parse by "### TagName" or "### EdgeName" headers
    sections = re.split(r"(?=^### )", full_schema, flags=re.MULTILINE)
    filtered_lines = [sections[0]]  # keep header line (# Schema for space...)

    for section in sections[1:]:
        if not section.strip():
            continue
        # Get the entity name from "### TagName" or "### EdgeName"
        header_match = re.match(r"^### (\w+)", section)
        if header_match:
            entity_name = header_match.group(1).lower()
            # Check if this entity matches any keyword
            is_tag = section.startswith("### Supplier") or section.startswith("### Invoice") or \
                     section.startswith("### Payment") or section.startswith("### PurchaseOrder") or \
                     section.startswith("### Receipt") or section.startswith("### Item") or \
                     section.startswith("### Organization") or section.startswith("### Employee") or \
                     section.startswith("### Currency") or section.startswith("### UOM") or \
                     section.startswith("### GLJournalEntry") or section.startswith("### BOM") or \
                     section.startswith("### Contract") or section.startswith("### SalesOrder") or \
                     section.startswith("### Shipment") or section.startswith("### ARInvoice") or \
                     section.startswith("### ARReceipt") or section.startswith("### SupplierQualification") or \
                     section.startswith("### ApprovalRecord") or section.startswith("### PurchaseRequisition")

            matches = False
            for kw in keywords:
                aliases = _ENTITY_KEYWORDS.get(kw, [kw])
                for alias in aliases:
                    if alias.lower() in entity_name:
                        matches = True
                        break
                if matches:
                    break

            if matches:
                filtered_lines.append(section)
        else:
            filtered_lines.append(section)

    filtered = "\n".join(filtered_lines)
    logger.debug("schema_filtered", original_len=len(full_schema), filtered_len=len(filtered), keywords=keywords)
    return filtered


def get_filtered_ontology_str(keywords: set[str]) -> str:
    """Load ontology text filtered to only relevant sections for the given keywords.

    Returns a concise ontology string containing only files/sections relevant to the question.
    """
    import re as _re

    ontology_dir = _PROMPTS_DIR / "ontology"
    if not ontology_dir.exists():
        return ""

    if not keywords:
        # Return empty rather than all - LLM should use schema primarily
        return ""

    # Determine which ontology files are relevant
    relevant_files: list[str] = []
    for filename, file_keywords in _ONTOLOGY_FILES.items():
        if keywords & file_keywords:
            relevant_files.append(filename)

    if not relevant_files:
        return ""

    parts = []
    for filename in sorted(relevant_files):
        filepath = ontology_dir / filename
        content = filepath.read_text(encoding="utf-8")

        # Remove code blocks (example ngql queries) to save space
        content = _re.sub(r"```ngql.*?```", "", content, flags=_re.DOTALL)
        content = _re.sub(r"```sql.*?```", "", content, flags=_re.DOTALL)
        content = _re.sub(r"```.*?```", "", content, flags=_re.DOTALL)

        # Remove example query sections (lines starting with --- or ### Query)
        lines = content.split("\n")
        filtered_lines = []
        skip_section = False
        for line in lines:
            if re.match(r"^---", line):
                skip_section = True
                continue
            if re.match(r"^## [A-Z].*Query", line):
                skip_section = True
                continue
            if re.match(r"^### Query", line):
                skip_section = True
                continue
            if re.match(r"^## [0-9]+\.", line):
                skip_section = False
            if not skip_section:
                filtered_lines.append(line)

        content = "\n".join(filtered_lines)
        # Compact multiple blank lines
        content = _re.sub(r"\n{3,}", "\n\n", content)

        stem = filepath.stem
        parts.append(f"# {stem}\n{content.strip()}\n")

    result = "\n".join(parts)
    logger.debug("ontology_filtered", original_files=len(list(ontology_dir.glob("*.md"))),
                  included_files=len(relevant_files), result_len=len(result))
    return result


async def get_schema_str(nebula: NebulaGraphClient, space: str = "honeybadge") -> str:
    """Get formatted NebulaGraph schema string."""
    if space in _schema_cache:
        return _schema_cache[space]

    lines = [f"# Schema for space: {space}\n"]

    # Tags
    tags_result = await nebula.execute("SHOW TAGS", space=space)
    tag_names = []
    if tags_result.success:
        for row in tags_result.rows:
            name = row.get("Name") or row.get("name") or ""
            if name:
                tag_names.append(str(name))

    lines.append("## Tags")
    for tag in tag_names:
        desc_result = await nebula.execute(f"DESCRIBE TAG `{tag}`", space=space)
        if desc_result.success:
            lines.append(f"### {tag}")
            for row in desc_result.rows:
                col = row.get("Field") or row.get("field") or ""
                typ = row.get("Type") or row.get("type") or ""
                null = row.get("Null") or row.get("null") or ""
                default = row.get("Default") or row.get("default") or ""
                extra = row.get("Extra") or row.get("extra") or ""
                props_str = f"{typ}"
                if null == "NO":
                    props_str += " NOT NULL"
                if default:
                    props_str += f" DEFAULT {default}"
                if extra:
                    props_str += f" {extra}"
                lines.append(f"  - {col}: {props_str}")

    # Edges
    edges_result = await nebula.execute("SHOW EDGES", space=space)
    edge_names = []
    if edges_result.success:
        for row in edges_result.rows:
            name = row.get("Name") or row.get("name") or ""
            if name:
                edge_names.append(str(name))

    lines.append("\n## Edges")
    for edge in edge_names:
        desc_result = await nebula.execute(f"DESCRIBE EDGE `{edge}`", space=space)
        if desc_result.success:
            lines.append(f"### {edge}")
            for row in desc_result.rows:
                col = row.get("Field") or row.get("field") or ""
                typ = row.get("Type") or row.get("type") or ""
                null = row.get("Null") or row.get("null") or ""
                default = row.get("Default") or row.get("default") or ""
                extra = row.get("Extra") or row.get("extra") or ""
                props_str = f"{typ}"
                if null == "NO":
                    props_str += " NOT NULL"
                if default:
                    props_str += f" DEFAULT {default}"
                if extra:
                    props_str += f" {extra}"
                lines.append(f"  - {col}: {props_str}")

    schema_str = "\n".join(lines)
    _schema_cache[space] = schema_str
    return schema_str


async def process_query(
    question: str,
    session_id: str,
    nebula: NebulaGraphClient,
    pg: PostgreSQLClient,
    llm_adapter: OpenAICompatibleAdapter,
    space: str = "honeybadge",
    user_id: str = "anonymous",
) -> dict[str, Any]:
    """
    Process a natural language query and return a result dict.

    Returns dict with: summary, raw_data, columns, cypher, trace_id, execution_time_ms, row_count
    """
    trace_id = generate_trace_id()
    start_time = time.time()

    logger.info("ws_query_start", trace_id=trace_id, question=question[:50])

    try:
        # Step 1: Extract keywords from question and get filtered schema + ontology
        keywords = _extract_keywords(question)
        logger.info("ws_query_keywords", trace_id=trace_id, keywords=sorted(keywords))

        schema_str = await get_filtered_schema_str(nebula, keywords, space)
        ontology_str = get_filtered_ontology_str(keywords)

        logger.info("ws_prompt_sizes", trace_id=trace_id,
                     schema_len=len(schema_str), ontology_len=len(ontology_str))

        # Step 2: Generate nGQL (raises LLMGenerationError on failure)
        ngql_response = await llm_generate_ngql(
            adapter=llm_adapter,
            question=question,
            schema_info=schema_str,
            ontology_info=ontology_str,
        )

        # Strip markdown code fences (e.g. ```ngql ... ```)
        ngql = _strip_markdown_fence(ngql_response.content)
        logger.info("ws_ngql_generated", trace_id=trace_id, ngql=ngql[:100])

        # Step 2b: L3 Permission enforcement (process ACL + org_id injection)
        if user_id in PERMISSION_CONFIG:
            perm_ctx = PERMISSION_CONFIG[user_id]
            ngql, perm_warnings = _permission_enforcer.enforce(ngql, perm_ctx)
            for w in perm_warnings:
                logger.info("ws_permission_filter", trace_id=trace_id, warning=w)

        # Step 3: Execute with retry on syntax/semantic errors
        max_retries = 2
        last_error = None
        for attempt in range(max_retries + 1):
            query_result = await nebula.execute(ngql, space=space)
            execution_time_ms = int((time.time() - start_time) * 1000)

            if query_result.success:
                break

            last_error = query_result.error_message
            logger.warning(
                "ws_ngql_execution_failed",
                trace_id=trace_id,
                attempt=attempt + 1,
                error=last_error,
                ngql=ngql[:100],
            )

            if attempt < max_retries:
                # Retry: pass broken query + error + explicit fix guidance
                error_hints = {
                    "optional match": "不要在 OPTIONAL MATCH 后加 WHERE，先用 MATCH 查出必要有数据的部分，再用 OPTIONAL MATCH 查可选部分",
                    "timed out": "查询太慢了，在 WHERE 条件后加 LIMIT 限制数量，或用更小的遍历深度",
                    "syntax error": "检查 nGQL 语法是否正确，确保每条 MATCH/OPTIONAL MATCH 语句的 WHERE 只跟在对应的 MATCH 后面",
                    "not found": "检查 Tag 和 Edge 名称是否拼写正确，注意大小写",
                }
                hint = ""
                for key, val in error_hints.items():
                    if key.lower() in str(last_error).lower():
                        hint = f"\n\n另外注意：{val}"
                enhanced_question = (
                    f"原始问题：{question}\n\n"
                    f"上次生成的nGQL查询（有问题）:\n```ngql\n{ngql}\n```\n"
                    f"执行失败，错误: {last_error}\n"
                    f"请根据错误信息修正nGQL，只返回正确的nGQL查询语句，不要解释。{hint}"
                )
                ngql_response = await llm_generate_ngql(
                    adapter=llm_adapter,
                    question=enhanced_question,
                    schema_info=schema_str,
                    ontology_info=ontology_str,
                )
                ngql = _strip_markdown_fence(ngql_response.content)
                logger.info("ws_ngql_retry", trace_id=trace_id, attempt=attempt + 2, ngql=ngql[:100])
        else:
            raise Exception(f"Query execution failed: {last_error}")

        # Step 4: Summarize (raises LLMSummarizationError on failure)
        summary_response = await llm_summarize_results(
            adapter=llm_adapter,
            question=question,
            raw_results=query_result.rows,
            columns=query_result.columns,
            trace_id=trace_id,
        )
        summary = re.sub(r"<think>.*?</think>", "", summary_response.content, flags=re.DOTALL).strip()

        # Step 5: Write audit log
        from honeybadge.db.postgres import AuditLogEntry

        try:
            audit_entry = AuditLogEntry(
                trace_id=trace_id,
                question=question,
                cypher=ngql,
                raw_result={"columns": query_result.columns, "rows": query_result.rows},
                summary=summary,
                user_id=user_id,
                session_id=session_id,
                execution_time_ms=execution_time_ms,
                row_count=query_result.row_count,
            )
            await pg.write_audit_log(audit_entry)
        except Exception as audit_err:
            logger.warning("ws_audit_write_failed", trace_id=trace_id, error=str(audit_err))

        logger.info(
            "ws_query_complete",
            trace_id=trace_id,
            execution_time_ms=execution_time_ms,
            row_count=query_result.row_count,
        )

        return {
            "summary": summary,
            "raw_data": query_result.rows,
            "columns": query_result.columns,
            "cypher": ngql,
            "trace_id": trace_id,
            "execution_time_ms": execution_time_ms,
            "row_count": query_result.row_count,
        }

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        logger.error("ws_query_error", trace_id=trace_id, error=str(e))

        # Try to write error audit
        try:
            from honeybadge.db.postgres import AuditLogEntry

            audit_entry = AuditLogEntry(
                trace_id=trace_id,
                question=question,
                cypher="",
                raw_result={"error": str(e)},
                summary=f"查询失败: {str(e)}",
                user_id=user_id,
                session_id=session_id,
                execution_time_ms=execution_time_ms,
                row_count=0,
                error_message=str(e),
            )
            await pg.write_audit_log(audit_entry)
        except Exception:
            pass

        return {
            "summary": f"查询处理失败: {str(e)}",
            "raw_data": [],
            "columns": [],
            "cypher": "",
            "trace_id": trace_id,
            "execution_time_ms": execution_time_ms,
            "row_count": 0,
            "error": str(e),
        }


def build_query_response(result: dict[str, Any]) -> dict[str, Any]:
    """Build a WSMessage QueryResponse from a query result dict."""
    return {
        "type": "response",
        "payload": {
            "summary": result["summary"],
            "raw_data": result["raw_data"],
            "columns": result["columns"],
            "cypher": result["cypher"],
            "trace_id": result["trace_id"],
            "execution_time_ms": result["execution_time_ms"],
            "row_count": result["row_count"],
        },
        "trace_id": result["trace_id"],
        "timestamp": int(time.time() * 1000),
    }
