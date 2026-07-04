"""Unit tests for the ERP connector abstraction layer.

Covers the ``ERPConnector`` ABC contract and the ``TableMapping``
dataclass, independent of any concrete connector implementation.
"""

from datetime import datetime

import pytest

from honeybadge.etl.connectors.base import ERPConnector, TableMapping


def test_table_mapping_builds_select_list_with_direct_mappings() -> None:
    """Direct column mappings produce ``SRC AS ods`` entries."""
    mapping = TableMapping(
        source_table="PO_HEADERS_ALL",
        watermark_column="LAST_UPDATE_DATE",
        column_mapping={
            "po_header_id": "PO_HEADER_ID",
            "po_number": "SEGMENT1",
        },
    )
    select_list = mapping.build_select_list()
    assert "PO_HEADER_ID AS po_header_id" in select_list
    assert "SEGMENT1 AS po_number" in select_list


def test_table_mapping_builds_select_list_with_derived_columns() -> None:
    """Derived columns wrap their expression in parentheses."""
    mapping = TableMapping(
        source_table="PO_HEADERS_ALL",
        watermark_column="LAST_UPDATE_DATE",
        column_mapping={"po_header_id": "PO_HEADER_ID"},
        derived_columns={
            "is_deleted": "CASE WHEN AUTHORIZATION_STATUS = 'CANCELLED' THEN 1 ELSE 0 END",
        },
    )
    select_list = mapping.build_select_list()
    assert "PO_HEADER_ID AS po_header_id" in select_list
    assert "(CASE WHEN AUTHORIZATION_STATUS = 'CANCELLED' THEN 1 ELSE 0 END) AS is_deleted" in select_list


def test_table_mapping_ods_columns_combines_mapped_and_derived() -> None:
    mapping = TableMapping(
        source_table="T",
        watermark_column="W",
        column_mapping={"a": "A", "b": "B"},
        derived_columns={"c": "A + B"},
    )
    assert set(mapping.ods_columns) == {"a", "b", "c"}


def test_table_mapping_defaults_source_system_to_ebs() -> None:
    mapping = TableMapping(source_table="T", watermark_column="W")
    assert mapping.source_system == "EBS"


def test_erp_connector_is_abstract() -> None:
    """ERPConnector cannot be instantiated directly."""
    with pytest.raises(TypeError):
        ERPConnector()  # type: ignore[abstract]


def test_erp_connector_subclass_must_implement_all_methods() -> None:
    """A subclass missing any method raises TypeError on instantiation."""

    class Incomplete(ERPConnector):
        async def connect(self) -> None:
            pass

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_erp_connector_full_subclass_instantiates() -> None:
    """A subclass implementing all abstract methods instantiates cleanly."""

    class Fake(ERPConnector):
        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

        async def extract(self, table, since=None, batch_size=1000):  # type: ignore[override]
            yield []

        async def get_source_watermark(self, table: str) -> datetime | None:
            return None

        async def health_check(self) -> bool:
            return True

    # Should not raise
    fake = Fake()
    assert fake is not None
