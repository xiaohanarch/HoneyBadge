"""Tests for trace module."""

import pytest

from honeybadge.core.trace import (
    generate_trace_id,
    is_valid_trace_id,
    parse_trace_id,
)


class TestGenerateTraceId:
    """Tests for generate_trace_id function."""

    def test_generates_valid_trace_id(self):
        """Should generate a valid trace ID."""
        trace_id = generate_trace_id()
        assert trace_id is not None
        assert len(trace_id) > 0

    def test_trace_id_has_correct_format(self):
        """Should generate trace ID with correct format."""
        trace_id = generate_trace_id()
        parts = trace_id.split("-")
        assert len(parts) == 4
        assert parts[0] == "TRC"

    def test_trace_id_with_custom_prefix(self):
        """Should generate trace ID with custom prefix."""
        trace_id = generate_trace_id(prefix="TEST")
        assert trace_id.startswith("TEST-")

    def test_trace_ids_are_unique(self):
        """Should generate unique trace IDs."""
        ids = [generate_trace_id() for _ in range(100)]
        assert len(set(ids)) == 100


class TestParseTraceId:
    """Tests for parse_trace_id function."""

    def test_parses_valid_trace_id(self):
        """Should parse a valid trace ID."""
        trace_id = "TRC-20260404-143022-a1b2c3d4"
        parsed = parse_trace_id(trace_id)

        assert parsed["prefix"] == "TRC"
        assert parsed["date"] == "20260404"
        assert parsed["time"] == "143022"
        assert parsed["uuid"] == "a1b2c3d4"

    def test_raises_error_for_invalid_format(self):
        """Should raise ValueError for invalid format."""
        with pytest.raises(ValueError):
            parse_trace_id("invalid")

    def test_raises_error_for_wrong_part_count(self):
        """Should raise ValueError for wrong number of parts."""
        with pytest.raises(ValueError):
            parse_trace_id("TRC-20260404-143022")


class TestIsValidTraceId:
    """Tests for is_valid_trace_id function."""

    def test_valid_trace_id_returns_true(self):
        """Should return True for valid trace ID."""
        assert is_valid_trace_id("TRC-20260404-143022-a1b2c3d4") is True

    def test_invalid_trace_id_returns_false(self):
        """Should return False for invalid trace ID."""
        assert is_valid_trace_id("invalid") is False
        assert is_valid_trace_id("TRC-20260404-143022") is False
        assert is_valid_trace_id("TRC-20260404-143022-too") is False
        assert is_valid_trace_id("TRC-2026040X-143022-a1b2c3d4") is False

    def test_trace_id_with_non_digit_date_returns_false(self):
        """Should return False for trace ID with non-digit date."""
        assert is_valid_trace_id("TRC-abcdefgh-143022-a1b2c3d4") is False
