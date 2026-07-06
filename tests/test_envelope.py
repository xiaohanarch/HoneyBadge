"""Unit tests for the unified response envelope."""

from honeybadge.server.envelope import ApiResponse, ErrorBody, error, success


class TestSuccessHelper:
    """Tests for the success() helper."""

    def test_success_returns_correct_shape(self):
        """success() should return {success: True, data, error: None, trace_id}."""
        result = success({"id": 1})
        assert result["success"] is True
        assert result["data"] == {"id": 1}
        assert result["error"] is None
        assert result["trace_id"] is None

    def test_success_with_trace_id(self):
        """success() should include trace_id when provided."""
        result = success("hello", trace_id="TRC-20260101-000000-aaaaaaaa")
        assert result["trace_id"] == "TRC-20260101-000000-aaaaaaaa"

    def test_success_with_none_data(self):
        """success() should accept None as data."""
        result = success(None)
        assert result["success"] is True
        assert result["data"] is None

    def test_success_with_list_data(self):
        """success() should accept a list as data."""
        result = success([1, 2, 3])
        assert result["data"] == [1, 2, 3]

    def test_success_trace_id_defaults_to_none(self):
        """success() should default trace_id to None."""
        result = success(42)
        assert result["trace_id"] is None


class TestErrorHelper:
    """Tests for the error() helper."""

    def test_error_returns_correct_shape(self):
        """error() should return {success: False, data: None, error, trace_id}."""
        result = error("VALIDATION_FAILED", "Bad input")
        assert result["success"] is False
        assert result["data"] is None
        assert result["error"]["code"] == "VALIDATION_FAILED"
        assert result["error"]["message"] == "Bad input"
        assert result["error"]["details"] is None
        assert result["trace_id"] is None

    def test_error_with_trace_id(self):
        """error() should include trace_id when provided."""
        result = error("INTERNAL_ERROR", "oops", trace_id="TRC-20260101-000000-bbbbbbbb")
        assert result["trace_id"] == "TRC-20260101-000000-bbbbbbbb"

    def test_error_with_details(self):
        """error() should include details when provided."""
        result = error("RATE_LIMIT_EXCEEDED", "Too many", details={"retry_after": 60})
        assert result["error"]["details"] == {"retry_after": 60}

    def test_error_trace_id_defaults_to_none(self):
        """error() should default trace_id to None."""
        result = error("NOT_FOUND", "missing")
        assert result["trace_id"] is None


class TestErrorBodyModel:
    """Tests for the ErrorBody pydantic model."""

    def test_error_body_requires_code_and_message(self):
        """ErrorBody should require code and message fields."""
        body = ErrorBody(code="TEST_CODE", message="test message")
        assert body.code == "TEST_CODE"
        assert body.message == "test message"
        assert body.details is None

    def test_error_body_accepts_details(self):
        """ErrorBody should accept optional details."""
        body = ErrorBody(code="TEST_CODE", message="test", details={"key": "value"})
        assert body.details == {"key": "value"}


class TestApiResponseModel:
    """Tests for the ApiResponse pydantic model."""

    def test_api_response_success_shape(self):
        """ApiResponse should model a success response correctly."""
        resp = ApiResponse[dict](success=True, data={"id": 1}, error=None, trace_id="t1")
        assert resp.success is True
        assert resp.data == {"id": 1}
        assert resp.error is None
        assert resp.trace_id == "t1"

    def test_api_response_error_shape(self):
        """ApiResponse should model an error response correctly."""
        err = ErrorBody(code="ERR", message="fail")
        resp = ApiResponse[dict](success=False, data=None, error=err, trace_id="t2")
        assert resp.success is False
        assert resp.data is None
        assert resp.error is not None
        assert resp.error.code == "ERR"
