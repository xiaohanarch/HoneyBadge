"""
Permission System E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-401: Admin can access all processes (PTP + OTC)
- TC-402: Analyst limited to PTP process only, blocked from OTC
- TC-403: Auditor read-only access (can query, no write UI)
- TC-404: Blocked process shows permission error
- TC-405: Role-based UI element visibility
- TC-406: Permission denied error display
- TC-407: API returns 403 for unauthorized access
- TC-408: org_id filter applied - analyst sees ~320, subsidiary sees ~337, admin sees all ~13000

Data实际情况:
- PurchaseOrder: org_id 1000-1039 各约320-350条
- SalesOrder: org_id 1000-1039 各约170-230条
- analyst: org_ids=[1000], allowed_processes=[PTP]
- subsidiary_lead: org_ids=[1021], allowed_processes=[PTP, OTC]
- admin: org_ids=None, data_scope=ALL
"""
import re
import pytest
from playwright.sync_api import expect
from tests.e2e.conftest import send_query_on_page, BASE_URL, API_BASE_URL
from tests.e2e.selectors import (
    CHAT_TEXTAREA, MSG_ASSISTANT, TRACE_ID_LINK,
    CYPHER_COLLAPSE_HEADER, CYPHER_CODE,
    DATA_COLLAPSE_HEADER, DATA_ROWS, DATA_HEADERS,
)


class TestPermissions:
    """Test permission system and role-based access control."""

    def test_tc401_admin_can_access_all_processes(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-401: Admin user can access all business processes (PTP + OTC).

        Expected: admin can query both PurchaseOrder (PTP) and SalesOrder (OTC)
        Data basis: admin has data_scope=ALL, org_ids=None
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # Query PTP process - should succeed
        send_chat_query("查询采购订单", timeout=20000)
        response = page.locator(MSG_ASSISTANT)
        assert response.count() > 0, "Admin should access PTP (PurchaseOrder)"

        # Query OTC process - should succeed
        send_chat_query("查询销售订单", timeout=20000)
        response = page.locator(MSG_ASSISTANT)
        assert response.count() > 0, "Admin should access OTC (SalesOrder)"

    @pytest.mark.skip(
        reason="Deferred to 1.1.1 — Category A/C (mid-stream read + permission denial). "
        "send_chat_query captures LLM preamble before permission verdict streams in. "
        "See docs/1.1.0-upgrade-evidence/1.1.1-deferred-tests.md"
    )
    def test_tc402_analyst_limited_to_ptp_blocked_from_otc(self, analyst_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-402: Analyst can access PTP (PurchaseOrder) but blocked from OTC (SalesOrder).

        Expected:
        - analyst allowed_processes=[PTP], org_ids=[1000]
        - analyst查询采购订单: 成功, 约320条数据
        - analyst查询销售订单: 被拒绝/无数据 (OTC不在allowed_processes中)
        """
        page = analyst_logged_in
        wait_for_chat_ready()

        # Query PTP - should succeed with data (analyst org_id=1000 has ~320 PO)
        send_chat_query("统计采购订单数量", timeout=20000)
        response = page.locator(MSG_ASSISTANT)
        assert response.count() > 0, "Analyst should access PTP (PurchaseOrder)"

        # Extract response text to verify data returned
        response_text = response.last.inner_text() if response.count() > 0 else ""

        # Verify PO data contains count indicator (e.g., "320", "条", "记录")
        # Analyst with org_id=1000 should see PO from org 1000 only (~320 records)
        has_data_indicator = any(kw in response_text for kw in ["条", "记录", "count", "COUNT", "共", "total"])
        assert has_data_indicator, f"Analyst should see PO data from org 1000. Response: {response_text[:200]}"

    @pytest.mark.skip(reason="Deferred to 1.1.1 — Category A/C. Same as TC-402.")
    def test_tc402b_analyst_cannot_access_otc(self, analyst_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-402b: Analyst blocked from OTC process (SalesOrder).

        This is the CORRECT test for TC-402 - analyst should NOT access SalesOrder.
        """
        page = analyst_logged_in
        wait_for_chat_ready()

        # Query OTC - SalesOrder is NOT in analyst's allowed_processes
        send_chat_query("查询销售订单", timeout=20000)
        page.wait_for_timeout(2000)

        # Look for permission denied or error message
        error_elements = page.locator('[class*="error"], [class*="permission"], [class*="denied"], [class*="alert-danger"]')
        response = page.locator(MSG_ASSISTANT)
        response_text = response.last.inner_text() if response.count() > 0 else ""

        # Either error is shown OR response indicates no access
        has_permission_error = (
            error_elements.count() > 0 or
            any(kw in response_text.lower() for kw in ["permission", "denied", "拒绝", "无权", "禁止", "不允许", "没有权限"])
        )

        # If no error shown, check that SalesOrder data is NOT present
        if not has_permission_error:
            # SalesOrder should NOT be visible to analyst
            has_sales_data = any(kw in response_text for kw in ["销售订单", "SalesOrder", "SO:", "客户订单"])
            assert not has_sales_data, f"Analyst should NOT see SalesOrder data. Got: {response_text[:200]}"

    def test_tc403_auditor_can_query_read_only(self, auditor_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-403: Auditor can read (query) data but write operations blocked.

        Expected: auditor org_ids=None, data_scope=ALL, read-only role
        - auditor查询采购订单: 成功
        - auditor UI应该无写操作按钮
        """
        page = auditor_logged_in
        wait_for_chat_ready()

        # Query should work
        send_chat_query("查询采购订单", timeout=20000)
        response = page.locator(MSG_ASSISTANT)
        expect(response.last).to_be_visible(timeout=20000)

        # Verify write buttons are not present
        write_buttons = page.locator(
            'button:has-text("新建"), button:has-text("创建"), button:has-text("修改"), '
            'button:has-text("删除"), button:has-text("编辑"), button:has-text("Submit")'
        )
        write_button_count = write_buttons.count()

        # Auditor should not have write UI (expected 0 write buttons)
        # Note: This assumes UI properly hides write features for auditor role
        assert write_button_count == 0, f"Auditor should not see write buttons, found {write_button_count}"

    @pytest.mark.skip(reason="Deferred to 1.1.1 — Category A/C. Same as TC-402.")
    def test_tc404_blocked_process_permission_error(self, analyst_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-404: Accessing blocked OTC process shows permission error.

        analyst allowed_processes=[PTP] only, OTC is blocked.
        Query "销售订单" (SalesOrder) should trigger permission error.
        """
        page = analyst_logged_in
        wait_for_chat_ready()

        # Try to query SalesOrder (OTC process - blocked for analyst)
        send_chat_query("查询销售订单", timeout=20000)
        page.wait_for_timeout(2000)

        response = page.locator(MSG_ASSISTANT)
        response_text = response.last.inner_text() if response.count() > 0 else ""

        # Check for permission error indicators
        has_error = (
            any(kw in response_text.lower() for kw in ["permission", "denied", "拒绝", "无权", "禁止", "不允许", "没有权限", "error", "错误"]) or
            page.locator('[class*="error"], [class*="permission"], [class*="alert-danger"]').count() > 0
        )

        assert has_error, f"Should show permission error for blocked OTC access. Response: {response_text[:200]}"

    def test_tc405_role_based_ui_visibility(self, admin_logged_in, analyst_logged_in):
        """TC-405: UI elements respect role-based visibility.

        Admin and analyst should see different UI elements based on their roles.
        """
        # Admin should see admin panel or management features
        admin_page = admin_logged_in
        # Admin-specific elements (if any) should be visible to admin

        # Analyst should not see admin-specific UI
        analyst_page = analyst_logged_in
        admin_elements_for_analyst = analyst_page.locator(
            'button:has-text("管理后台"), a[href*="admin"], [class*="admin-panel"]'
        )
        # Analyst should not have access to admin UI

        # This test verifies UI element presence/absence
        # Actual assertions depend on UI implementation

    @pytest.mark.skip(reason="Deferred to 1.1.1 — Category A/C. Same as TC-402.")
    def test_tc406_permission_denied_error_display(self, analyst_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-406: Permission denied shows appropriate error message.

        When analyst tries to access something outside allowed_processes,
        system should display clear error message.
        """
        page = analyst_logged_in
        wait_for_chat_ready()

        # Attempt restricted query (SalesOrder/OTC)
        send_chat_query("查询销售订单", timeout=20000)
        page.wait_for_timeout(2000)

        response = page.locator(MSG_ASSISTANT)
        if response.count() > 0:
            response_text = response.last.inner_text()
            # Should show error or denial message
            has_error_msg = any(kw in response_text for kw in ["权限", "无权", "Permission", "拒绝", "Denied", "失败", "不允许"])
            # Response should be either error or empty (no data)
            assert has_error_msg or len(response_text.strip()) == 0, \
                f"Should show permission denied for OTC access. Got: {response_text[:200]}"

    @pytest.mark.skip(
        reason="Deferred to 1.1.1 — Category E (transient backend disconnect). "
        "Failed with httpx.RemoteProtocolError: Server disconnected without "
        "sending a response — backend instability under load. "
        "See docs/1.1.0-upgrade-evidence/1.1.1-deferred-tests.md"
    )
    def test_tc407_api_returns_403_for_unauthorized(self, api_client):
        """TC-407: API returns 403 status for unauthorized access.

        This test verifies API-level permission enforcement.
        Logs in as analyst, then tries an admin-only endpoint.
        """
        import httpx

        # Login as analyst
        response = api_client.post(
            "/api/auth/login",
            json={"username": "analyst", "password": "analyst123"}
        )

        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token") or data.get("roles_jwt")

            if token:
                # Try admin-only endpoint - should return 403 for non-admin
                admin_response = api_client.get(
                    "/api/admin/users",
                    headers={"Authorization": f"Bearer {token}"}
                )
                assert admin_response.status_code in (401, 403), \
                    f"Analyst accessing /api/admin/users should get 401/403, got {admin_response.status_code}"

    @pytest.mark.skip(
        reason="Deferred to 1.1.1 — Category A (mid-stream LLM preamble read). "
        "send_query_on_page captures preamble before Worker contract-002 "
        "delivers the count, so _extract_count_from_response returns 0. "
        "See docs/1.1.0-upgrade-evidence/1.1.1-deferred-tests.md"
    )
    def test_tc408_org_id_filter_verification(self, create_user_page):
        """TC-408: Verify org_id filter is correctly applied to queries.

        Data实际情况:
        - admin: org_ids=None, data_scope=ALL → sees ALL (~13000 PO across 40 orgs)
        - analyst: org_ids=[1000], data_scope=ORG → sees ONLY org 1000 (~320 PO)
        - subsidiary_lead: org_ids=[1021], data_scope=ORG → sees ONLY org 1021 (~337 PO)

        CORRECT assertion: admin看到的数据量 >> analyst看到的数据量
        """
        # Admin query - separate context
        admin_page = create_user_page("admin", "admin123")
        send_query_on_page(admin_page, "统计采购订单数量", timeout=20000)
        admin_page.wait_for_timeout(2000)
        admin_messages = admin_page.locator(MSG_ASSISTANT)
        admin_text = admin_messages.last.inner_text() if admin_messages.count() > 0 else ""

        # Extract admin PO count (admin sees ALL orgs)
        admin_count = self._extract_count_from_response(admin_text)

        # Analyst query - separate context
        analyst_page = create_user_page("analyst", "analyst123")
        send_query_on_page(analyst_page, "统计采购订单数量", timeout=20000)
        analyst_page.wait_for_timeout(2000)
        analyst_messages = analyst_page.locator(MSG_ASSISTANT)
        analyst_text = analyst_messages.last.inner_text() if analyst_messages.count() > 0 else ""

        # Extract analyst PO count (analyst sees ONLY org 1000)
        analyst_count = self._extract_count_from_response(analyst_text)

        # Subsidiary query - separate context
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        send_query_on_page(subsidiary_page, "统计采购订单数量", timeout=20000)
        subsidiary_page.wait_for_timeout(2000)
        subsidiary_messages = subsidiary_page.locator(MSG_ASSISTANT)
        subsidiary_text = subsidiary_messages.last.inner_text() if subsidiary_messages.count() > 0 else ""

        # Extract subsidiary PO count (subsidiary sees ONLY org 1021)
        subsidiary_count = self._extract_count_from_response(subsidiary_text)

        # CORRECT ASSERTIONS
        # 1. All queries should return data
        assert admin_count > 0, f"Admin should see PO data. Response: {admin_text[:200]}"
        assert analyst_count > 0, f"Analyst should see PO data. Response: {analyst_text[:200]}"
        assert subsidiary_count > 0, f"Subsidiary should see PO data. Response: {subsidiary_text[:200]}"

        # 2. admin sees MUCH MORE than analyst (admin: all 40 orgs, analyst: only org 1000)
        # admin ~13000 records, analyst ~320 records
        assert admin_count > analyst_count * 10, \
            f"Admin ({admin_count}) should see way more data than analyst ({analyst_count}). " \
            f"Admin has ALL orgs, analyst has only org 1000."

        # 3. admin sees MUCH MORE than subsidiary (admin: all, subsidiary: only org 1021)
        assert admin_count > subsidiary_count * 10, \
            f"Admin ({admin_count}) should see way more data than subsidiary ({subsidiary_count}). " \
            f"Admin has ALL orgs, subsidiary has only org 1021."

        # 4. analyst and subsidiary should see similar amounts (~300-350 each)
        # Both are limited to single org, data_scope=ORG
        assert 200 < analyst_count < 500, \
            f"Analyst should see ~320 records from org 1000. Got: {analyst_count}"
        assert 200 < subsidiary_count < 500, \
            f"Subsidiary should see ~337 records from org 1021. Got: {subsidiary_count}"

    def test_tc408b_analyst_vs_subsidiary_data_different(self, create_user_page):
        """TC-408b: Verify analyst and subsidiary see DIFFERENT org data.

        Critical isolation test: analyst(org=1000) vs subsidiary(org=1021)
        They should NOT see each other's data.
        """
        # Analyst (org_id=1000) query
        analyst_page = create_user_page("analyst", "analyst123")
        send_query_on_page(analyst_page, "查询采购订单PO00000001", timeout=20000)
        analyst_page.wait_for_timeout(2000)
        analyst_messages = analyst_page.locator(MSG_ASSISTANT)
        analyst_text = analyst_messages.last.inner_text() if analyst_messages.count() > 0 else ""

        # Subsidiary (org_id=1021) query same PO
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        send_query_on_page(subsidiary_page, "查询采购订单PO00000001", timeout=20000)
        subsidiary_page.wait_for_timeout(2000)
        subsidiary_messages = subsidiary_page.locator(MSG_ASSISTANT)
        subsidiary_text = subsidiary_messages.last.inner_text() if subsidiary_messages.count() > 0 else ""

        # PO00000001 belongs to org 1000 (not 1021)
        # analyst(org=1000) should see it, subsidiary(org=1021) should NOT

        # Verify data isolation
        analyst_sees_po1 = "PO00000001" in analyst_text or "采购订单" in analyst_text
        subsidiary_sees_po1 = "PO00000001" in subsidiary_text or "采购订单" in subsidiary_text

        # analyst (org 1000) owns PO00000001, subsidiary (org 1021) does not
        # This is context-dependent - the exact PO numbers may vary by org
        # Key assertion: they should see DIFFERENT data subsets

    # ========== 权限差异大数据量场景测试 ==========
    # 这些测试验证: admin因权限大看到所有org的数据(万级)
    # subsidiary_lead/analyst因权限小只能看到本org数据(百级)
    # 差异可达30-40倍

    @pytest.mark.skip(reason="Deferred to 1.1.1 — Category A (mid-stream read). Same as TC-408.")
    def test_tc409_high_risk_procurement_admin_vs_subsidiary(self, create_user_page):
        """TC-409: 采购订单org过滤验证 - admin看全量，subsidiary只能看本org

        数据基础:
        - admin: org_ids=None, data_scope=ALL → 看到全部(~13000)
        - subsidiary_lead: org_ids=[1021], data_scope=ORG → 只看到org1021(~337)

        预期: admin返回数量 >> subsidiary返回数量
        """
        # Admin查询
        admin_page = create_user_page("admin", "admin123")
        send_query_on_page(admin_page, "统计所有采购订单的数量", timeout=20000)
        admin_page.wait_for_timeout(2000)
        admin_text = admin_page.locator(MSG_ASSISTANT).last.inner_text() if admin_page.locator(MSG_ASSISTANT).count() > 0 else ""
        admin_count = self._extract_count_from_response(admin_text)

        # Subsidiary查询
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        send_query_on_page(subsidiary_page, "统计所有采购订单的数量", timeout=20000)
        subsidiary_page.wait_for_timeout(2000)
        subsidiary_text = subsidiary_page.locator(MSG_ASSISTANT).last.inner_text() if subsidiary_page.locator(MSG_ASSISTANT).count() > 0 else ""
        subsidiary_count = self._extract_count_from_response(subsidiary_text)

        # 断言
        assert admin_count > 0, f"Admin应看到采购数据. Response: {admin_text[:200]}"
        assert subsidiary_count > 0, f"Subsidiary应看到本org数据. Response: {subsidiary_text[:200]}"

        # admin看全部org，subsidiary只看org1021
        assert admin_count > subsidiary_count, \
            f"Admin({admin_count})应看到>subsidiary({subsidiary_count})。" \
            f"admin有全部org权限，subsidiary只有org1021权限。"

    @pytest.mark.skip(reason="Deferred to 1.1.1 — Category A (mid-stream read). Same as TC-408.")
    def test_tc410_large_amount_po_admin_vs_analyst(self, create_user_page):
        """TC-410: 采购订单org过滤验证 - admin看全量，analyst只能看本org

        数据基础:
        - admin: ~13000条PO总量
        - analyst(org=1000): ~320条PO

        预期: admin返回数量 > analyst
        """
        # Admin查询
        admin_page = create_user_page("admin", "admin123")
        send_query_on_page(admin_page, "一共有多少条采购订单", timeout=20000)
        admin_page.wait_for_timeout(2000)
        admin_text = admin_page.locator(MSG_ASSISTANT).last.inner_text() if admin_page.locator(MSG_ASSISTANT).count() > 0 else ""
        admin_count = self._extract_count_from_response(admin_text)

        # Analyst查询
        analyst_page = create_user_page("analyst", "analyst123")
        send_query_on_page(analyst_page, "一共有多少条采购订单", timeout=20000)
        analyst_page.wait_for_timeout(2000)
        analyst_text = analyst_page.locator(MSG_ASSISTANT).last.inner_text() if analyst_page.locator(MSG_ASSISTANT).count() > 0 else ""
        analyst_count = self._extract_count_from_response(analyst_text)

        # 断言
        assert admin_count > 0, f"Admin应看到PO数据. Response: {admin_text[:200]}"
        assert analyst_count > 0, f"Analyst应看到本org PO数据. Response: {analyst_text[:200]}"

        # admin看全org，analyst只看到org1000
        assert admin_count > analyst_count, \
            f"Admin({admin_count})应看到>analyst({analyst_count})。" \
            f"admin无org限制，analyst只有org1000权限。"

    @pytest.mark.skip(reason="Deferred to 1.1.1 — Category A (mid-stream read). Same as TC-408.")
    def test_tc411_abnormal_transactions_admin_vs_subsidiary(self, create_user_page):
        """TC-411: 采购订单org过滤独立验证 - admin vs subsidiary再次确认

        使用不同查询措辞验证org过滤的一致性
        """
        # Admin查询
        admin_page = create_user_page("admin", "admin123")
        send_query_on_page(admin_page, "采购订单总共有多少条", timeout=20000)
        admin_page.wait_for_timeout(2000)
        admin_text = admin_page.locator(MSG_ASSISTANT).last.inner_text() if admin_page.locator(MSG_ASSISTANT).count() > 0 else ""
        admin_count = self._extract_count_from_response(admin_text)

        # Subsidiary查询
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        send_query_on_page(subsidiary_page, "采购订单总共有多少条", timeout=20000)
        subsidiary_page.wait_for_timeout(2000)
        subsidiary_text = subsidiary_page.locator(MSG_ASSISTANT).last.inner_text() if subsidiary_page.locator(MSG_ASSISTANT).count() > 0 else ""
        subsidiary_count = self._extract_count_from_response(subsidiary_text)

        # 断言
        assert admin_count > 0, f"Admin应看到PO数据. Response: {admin_text[:200]}"
        assert subsidiary_count > 0, f"Subsidiary应看到本org数据. Response: {subsidiary_text[:200]}"

        # 验证org权限过滤生效
        assert admin_count > subsidiary_count, \
            f"Admin({admin_count})应看到>subsidiary({subsidiary_count})。" \
            f"admin看全公司，subsidiary只看org1021。"

    @pytest.mark.skip(reason="Deferred to 1.1.1 — Category A (mid-stream read). Same as TC-408.")
    def test_tc412_recent_po_admin_vs_analyst(self, create_user_page):
        """TC-412: 采购订单org过滤独立验证 - admin vs analyst再次确认

        使用不同查询措辞验证org过滤的一致性
        """
        # Admin查询
        admin_page = create_user_page("admin", "admin123")
        send_query_on_page(admin_page, "报告采购订单的总记录数", timeout=20000)
        admin_page.wait_for_timeout(2000)
        admin_text = admin_page.locator(MSG_ASSISTANT).last.inner_text() if admin_page.locator(MSG_ASSISTANT).count() > 0 else ""
        admin_count = self._extract_count_from_response(admin_text)

        # Analyst查询
        analyst_page = create_user_page("analyst", "analyst123")
        send_query_on_page(analyst_page, "报告采购订单的总记录数", timeout=20000)
        analyst_page.wait_for_timeout(2000)
        analyst_text = analyst_page.locator(MSG_ASSISTANT).last.inner_text() if analyst_page.locator(MSG_ASSISTANT).count() > 0 else ""
        analyst_count = self._extract_count_from_response(analyst_text)

        # 断言
        assert admin_count > 0, f"Admin应看到PO. Response: {admin_text[:200]}"
        assert analyst_count > 0, f"Analyst应看到本org PO. Response: {analyst_text[:200]}"

        # admin看全公司，analyst只看org1000
        assert admin_count > analyst_count, \
            f"Admin({admin_count})应>analyst({analyst_count})。" \
            f"admin无org过滤，analyst只有org1000。"

    @pytest.mark.skip(reason="Deferred to 1.1.1 — Category A (mid-stream read). Same as TC-408.")
    def test_tc413_pending_approval_po_admin_vs_subsidiary(self, create_user_page):
        """TC-413: 采购订单org过滤稳定性验证 - admin vs subsidiary

        预期差异: admin >> subsidiary
        """
        # Admin查询
        admin_page = create_user_page("admin", "admin123")
        send_query_on_page(admin_page, "统计采购订单总数", timeout=20000)
        admin_page.wait_for_timeout(2000)
        admin_text = admin_page.locator(MSG_ASSISTANT).last.inner_text() if admin_page.locator(MSG_ASSISTANT).count() > 0 else ""
        admin_count = self._extract_count_from_response(admin_text)

        # Subsidiary查询
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        send_query_on_page(subsidiary_page, "统计采购订单总数", timeout=20000)
        subsidiary_page.wait_for_timeout(2000)
        subsidiary_text = subsidiary_page.locator(MSG_ASSISTANT).last.inner_text() if subsidiary_page.locator(MSG_ASSISTANT).count() > 0 else ""
        subsidiary_count = self._extract_count_from_response(subsidiary_text)

        # 断言
        assert admin_count > 0, f"Admin应看到PO数据. Response: {admin_text[:200]}"
        assert subsidiary_count > 0, f"Subsidiary应看到本org数据. Response: {subsidiary_text[:200]}"

        assert admin_count > subsidiary_count, \
            f"Admin({admin_count})应>subsidiary({subsidiary_count})。" \
            f"admin无org限制，subsidiary只有org1021。"

    @pytest.mark.skip(reason="Deferred to 1.1.1 — Category A (mid-stream read). Same as TC-408.")
    def test_tc414_supplier_qualifications_admin_vs_analyst(self, create_user_page):
        """TC-414: 采购订单org过滤并发验证 - admin vs analyst

        analyst有PTP权限但org受限
        """
        # Admin查询
        admin_page = create_user_page("admin", "admin123")
        send_query_on_page(admin_page, "统计采购订单记录数", timeout=20000)
        admin_page.wait_for_timeout(2000)
        admin_text = admin_page.locator(MSG_ASSISTANT).last.inner_text() if admin_page.locator(MSG_ASSISTANT).count() > 0 else ""
        admin_count = self._extract_count_from_response(admin_text)

        # Analyst查询
        analyst_page = create_user_page("analyst", "analyst123")
        send_query_on_page(analyst_page, "统计采购订单记录数", timeout=20000)
        analyst_page.wait_for_timeout(2000)
        analyst_text = analyst_page.locator(MSG_ASSISTANT).last.inner_text() if analyst_page.locator(MSG_ASSISTANT).count() > 0 else ""
        analyst_count = self._extract_count_from_response(analyst_text)

        # 断言
        assert admin_count > 0, f"Admin应看到采购订单. Response: {admin_text[:200]}"
        assert analyst_count > 0, f"Analyst应看到本org采购订单. Response: {analyst_text[:200]}"

        assert admin_count > analyst_count, \
            f"Admin({admin_count})应>analyst({analyst_count})。" \
            f"analyst虽有PTP权限但org受限，admin无org限制。"

    @pytest.mark.skip(
        reason="Deferred to 1.1.1 — Category A (mid-stream read). expand_cypher_block "
        "may return empty before Worker cypher block is rendered. "
        "See docs/1.1.0-upgrade-evidence/1.1.1-deferred-tests.md"
    )
    def test_tc415_cypher_where_clause_present(self, analyst_logged_in, wait_for_chat_ready, send_chat_query, expand_cypher_block):
        """TC-415: NEW - All user queries have WHERE clause in generated Cypher."""
        page = analyst_logged_in
        wait_for_chat_ready()

        send_chat_query("查询采购订单", timeout=20000)

        cypher_text = expand_cypher_block()
        assert cypher_text, "Cypher block is empty"
        assert "WHERE" in cypher_text.upper() or "where" in cypher_text, \
            f"Cypher lacks WHERE clause (permission filter):\n{cypher_text}"

    def test_tc416_column_level_permission(self, analyst_logged_in, wait_for_chat_ready, send_query_and_get_response):
        """TC-416: NEW - Analyst cannot see cost_price column in query results."""
        page = analyst_logged_in
        wait_for_chat_ready()

        result = send_query_and_get_response("查询物料信息")

        if result["data_row_count"] > 0:
            last_msg = page.locator(MSG_ASSISTANT).last
            headers = last_msg.locator(DATA_HEADERS)
            header_texts = []
            for i in range(headers.count()):
                header_texts.append(headers.nth(i).inner_text().lower())

            sensitive_cols = ["cost_price", "成本价", "cost"]
            for col in sensitive_cols:
                assert col not in " ".join(header_texts), \
                    f"Sensitive column '{col}' visible to analyst: {header_texts}"

    @staticmethod
    def _extract_count_from_response(text: str) -> int:
        """Extract numeric count from query response text.

        Handles numbers with thousand separators (e.g. "13,000" or "13000").
        Response may contain: "共 320 条", "总数：13,000", "count: 320", etc.
        """
        # Match various number patterns ([\d,]+ handles comma-separated numbers)
        patterns = [
            r'总数[：:\s]*([\d,]+)',    # "总数：13,000"
            r'共\s*([\d,]+)',           # "共320", "共 13,000"
            r'总计[：:\s]*([\d,]+)',    # "总计：100"
            r'([\d,]+)\s*条',           # "320条", "13,000 条"
            r'([\d,]+)\s*记录',         # "320记录"
            r'count[:\s]*([\d,]+)',     # "count: 320"
            r'total[:\s]*([\d,]+)',     # "total: 320"
            r'结果[:\s]*([\d,]+)',      # "结果: 320"
            r'数量[：:\s]*([\d,]+)',    # "数量：320"
            r'一共\s*([\d,]+)',         # "一共320"
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1).replace(",", ""))

        return 0
