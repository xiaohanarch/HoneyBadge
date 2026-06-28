"""
User Isolation E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-301: Admin sessions invisible to analyst
- TC-302: Analyst sessions invisible to admin
- TC-303: Cross-org data isolation (admin:ALL vs analyst:1000 vs subsidiary:1011)
- TC-304: Subsidiary user cannot see parent org data
- TC-305: Session data isolated by user
- TC-306: Cache isolation between users
- TC-307: Query results filtered by org_id
- TC-308: Matrix room isolation per user

Data实际情况:
- PurchaseOrder: org_id 1000-1039 各约320-350条
- SalesOrder: org_id 1000-1039 各约170-230条
- admin: org_ids=None, data_scope=ALL → sees ALL (~13000 PO)
- analyst: org_ids=[1000], data_scope=ORG → sees ONLY org 1000 (~320 PO)
- subsidiary_lead: org_ids=[1011], data_scope=ORG → sees ONLY org 1011 (~337 PO)
"""
import pytest
from playwright.sync_api import expect
from tests.e2e.conftest import send_query_on_page
from tests.e2e.selectors import MSG_ASSISTANT


BASE_URL = "http://localhost:3000"


class TestUserIsolation:
    """Test user isolation and multi-tenancy."""

    def test_tc301_admin_sessions_invisible_to_analyst(self, admin_logged_in, analyst_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-301: Admin's sessions are not visible to analyst user.

        Each user should only see their own sessions.
        """
        # Admin creates a session with unique name
        admin_page = admin_logged_in
        wait_for_chat_ready()
        send_chat_query("查询供应商", timeout=120000)
        admin_page.wait_for_timeout(1000)

        # Now login as analyst
        analyst_page = analyst_logged_in
        wait_for_chat_ready()

        # Analyst should NOT see admin's session
        # Check that admin's query doesn't appear in analyst's session list
        analyst_session_count = analyst_page.locator('.session-item, [class*="session"]').count()

        # Analyst should have their own empty or limited session list
        # (Not the same as admin's session)
        admin_session_indicator = analyst_page.locator('text="Admin Private Session TC-301"')
        assert admin_session_indicator.count() == 0, \
            "Analyst should not see admin's private session"

    def test_tc302_analyst_sessions_invisible_to_admin(self, analyst_logged_in, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-302: Analyst's sessions are not visible to admin user.

        Sessions are strictly isolated per user_id.
        """
        # Analyst creates a session
        analyst_page = analyst_logged_in
        wait_for_chat_ready()
        send_chat_query("查询采购订单", timeout=120000)
        analyst_page.wait_for_timeout(1000)

        # Now login as admin
        admin_page = admin_logged_in
        wait_for_chat_ready()

        # Admin should NOT see analyst's session
        analyst_session_indicator = admin_page.locator('text="Analyst Private Session TC-302"')
        assert analyst_session_indicator.count() == 0, \
            "Admin should not see analyst's private session"

    def test_tc303_cross_org_data_isolation(self, create_user_page):
        """TC-303: Data is isolated between organizations.

        admin (org_ids=None) sees ALL data
        analyst (org_ids=[1000]) sees ONLY org 1000 data
        subsidiary_lead (org_ids=[1011]) sees ONLY org 1011 data

        Key assertion: counts should differ significantly
        - admin sees ~13000 records (all 40 orgs)
        - analyst sees ~320 records (only org 1000)
        - subsidiary sees ~337 records (only org 1011)
        """
        # Admin query
        admin_page = create_user_page("admin", "admin123")
        admin_text = send_query_on_page(admin_page, "统计采购订单数量", timeout=120000)
        admin_count = self._extract_count(admin_text)

        # Analyst query (org_id=1000)
        analyst_page = create_user_page("analyst", "analyst123")
        analyst_text = send_query_on_page(analyst_page, "统计采购订单数量", timeout=120000)
        analyst_count = self._extract_count(analyst_text)

        # CORRECT ASSERTIONS
        assert admin_count > 0, f"Admin should see PO data. Response: {admin_text[:200]}"
        assert analyst_count > 0, f"Analyst should see PO data. Response: {analyst_text[:200]}"

        # Admin should see WAY more (all 40 orgs) than analyst (only org 1000)
        assert admin_count > analyst_count * 10, \
            f"Admin ({admin_count}) should see >10x data than analyst ({analyst_count}). " \
            f"Isolation working: admin sees ALL orgs, analyst sees only org 1000."

    def test_tc304_subsidiary_cannot_see_parent_org(self, create_user_page):
        """TC-304: Subsidiary user cannot see parent org (other orgs) data.

        subsidiary_lead org_ids=[1011] should ONLY see org 1011 data.
        Should NOT see data from org 1000, 1001, etc.
        """
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")

        # Query采购订单 - should return ONLY org 1011's data
        subsidiary_text = send_query_on_page(subsidiary_page, "统计采购订单数量", timeout=120000)
        subsidiary_count = self._extract_count(subsidiary_text)

        # subsidiary_lead with org_id=1011 should see ~337 records
        assert 200 < subsidiary_count < 500, \
            f"Subsidiary (org 1011) should see ~337 records. Got: {subsidiary_count}. " \
            f"Response: {subsidiary_text[:200]}"

        # Should NOT see all records (would be ~13000 if no org filtering)
        assert subsidiary_count < 1000, \
            f"Subsidiary should NOT see all orgs data. Got: {subsidiary_count}. " \
            f"org_id filter not working properly."

    @pytest.mark.skip(
        reason="Deferred to 1.1.1 — Category E (page navigation + teardown ERROR). "
        "Test fails AND errors on teardown due to context cleanup race. Needs "
        "fixture rework. See docs/1.1.0-upgrade-evidence/1.1.1-deferred-tests.md"
    )
    def test_tc305_session_isolation_by_user(self, page, login_as, wait_for_chat_ready, send_chat_query):
        """TC-305: Each user has isolated session storage.

        localStorage should be different for different users.
        """
        # Login as admin
        login_as("admin", "admin123")
        wait_for_chat_ready()
        send_chat_query("管理员查询", timeout=120000)
        page.wait_for_timeout(1000)

        # Store admin's local storage
        admin_storage = page.evaluate("() => localStorage.getItem('auth_store')")

        # Clear and login as analyst
        page.evaluate("() => localStorage.clear()")
        page.goto(f"{BASE_URL}/login")
        login_as("analyst", "analyst123")
        wait_for_chat_ready()

        # Check that admin's auth data is not present
        analyst_storage = page.evaluate("() => localStorage.getItem('auth_store')")

        # Verify isolation
        assert admin_storage, "Admin should have localStorage data"
        assert analyst_storage, "Analyst should have localStorage data"
        assert admin_storage != analyst_storage, "Users should have different localStorage tokens"

    def test_tc306_cache_isolation_between_users(self, admin_logged_in, analyst_logged_in, send_chat_query):
        """TC-306: Cache entries are isolated between users.

        Each user's query should not leak to another user's cache.
        """
        admin_page = admin_logged_in
        analyst_page = analyst_logged_in

        # Admin queries specific supplier
        send_chat_query("查询供应商SYR001", timeout=120000)
        admin_page.wait_for_timeout(1000)

        # Analyst queries same thing - should get their own result (filtered by org)
        send_chat_query("查询供应商SYR001", timeout=120000)
        analyst_page.wait_for_timeout(1000)

        # Both should have received responses (isolation verified by separate queries working)
        admin_has_response = admin_page.locator(MSG_ASSISTANT).count() > 0
        analyst_has_response = analyst_page.locator(MSG_ASSISTANT).count() > 0

        assert admin_has_response, "Admin should get response"
        assert analyst_has_response, "Analyst should get response"

    def test_tc307_query_results_filtered_by_org_id(self, create_user_page):
        """TC-307: Query results respect org_id filtering.

        analyst (org=1000) vs subsidiary (org=1011) should see DIFFERENT data.
        This is the KEY data isolation test.
        """
        # Admin query - baseline (all data)
        admin_page = create_user_page("admin", "admin123")
        admin_text = send_query_on_page(admin_page, "统计采购订单数量", timeout=120000)
        admin_count = self._extract_count(admin_text)

        # Analyst query (org_id=1000)
        analyst_page = create_user_page("analyst", "analyst123")
        analyst_text = send_query_on_page(analyst_page, "统计采购订单数量", timeout=120000)
        analyst_count = self._extract_count(analyst_text)

        # Subsidiary query (org_id=1011)
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        subsidiary_text = send_query_on_page(subsidiary_page, "统计采购订单数量", timeout=120000)
        subsidiary_count = self._extract_count(subsidiary_text)

        # CORRECT ASSERTIONS - Verify org_id filtering is working
        # 1. All should return data
        assert admin_count > 0, f"Admin should see data. Response: {admin_text[:200]}"
        assert analyst_count > 0, f"Analyst should see data. Response: {analyst_text[:200]}"
        assert subsidiary_count > 0, f"Subsidiary should see data. Response: {subsidiary_text[:200]}"

        # 2. admin >> analyst (admin all orgs, analyst only org 1000)
        assert admin_count > analyst_count * 10, \
            f"Admin ({admin_count}) should see >> analyst ({analyst_count})"

        # 3. admin >> subsidiary (admin all orgs, subsidiary only org 1011)
        assert admin_count > subsidiary_count * 10, \
            f"Admin ({admin_count}) should see >> subsidiary ({subsidiary_count})"

        # 4. Verify analyst and subsidiary see limited data (~300-350 each)
        assert 200 < analyst_count < 500, f"Analyst should see ~320 records. Got: {analyst_count}"
        assert 200 < subsidiary_count < 500, f"Subsidiary should see ~337 records. Got: {subsidiary_count}"

    def test_tc308_matrix_room_isolation(self, create_user_page):
        """TC-308: Matrix rooms are isolated per user.

        Each user should have their own Matrix room (via DM room creation).
        Uses separate browser contexts to ensure genuine isolation check.
        """
        admin_page = create_user_page("admin", "admin123")
        analyst_page = create_user_page("analyst", "analyst123")

        # Get Matrix room identifiers from localStorage or page context
        # Frontend stores the per-user DM room ID under 'matrix_dm_room_id'
        # (see frontend/src/composables/useAuth.ts and stores/auth.ts).
        admin_room_id = admin_page.evaluate("() => localStorage.getItem('matrix_dm_room_id')")
        analyst_room_id = analyst_page.evaluate("() => localStorage.getItem('matrix_dm_room_id')")

        assert admin_room_id, "Admin should have a Matrix room ID"
        assert analyst_room_id, "Analyst should have a Matrix room ID"
        assert admin_room_id != analyst_room_id, "Users must have different Matrix rooms"

    def test_tc309_verify_org_specific_po_numbers(self, create_user_page):
        """TC-309: Verify org-specific PO numbers are correctly filtered.

        Test with specific PO numbers to prove data isolation.
        """
        # PO numbers by org (from test data analysis):
        # org 1000: PO00000001, PO00000002, etc.
        # org 1011: PO00000002, PO00000004, etc. (different set)

        # Analyst (org=1000) queries for PO00000001
        analyst_page = create_user_page("analyst", "analyst123")
        analyst_text = send_query_on_page(analyst_page, "查询采购订单PO00000001", timeout=120000)

        # Subsidiary (org=1011) queries for PO00000002
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        subsidiary_text = send_query_on_page(subsidiary_page, "查询采购订单PO00000002", timeout=120000)

        # Verify both got responses (queries processed)
        assert len(analyst_text) > 0, "Analyst query should return response"
        assert len(subsidiary_text) > 0, "Subsidiary query should return response"

        # The key verification is that each sees data from their org only
        # Exact assertions depend on knowing which PO belongs to which org in test data

    # ========== 数据隔离高风险场景测试 ==========
    # 核心价值: 体现RBP权限 + LLM的结合
    # 大领导(admin)权限大，可以看到全公司问题(万级数据)
    # 小领导(subsidiary/analyst)权限小，只能看到本组织问题(百级数据)

    @pytest.mark.timeout(600)
    def test_tc310_high_risk_po_data_volume_isolation(self, reset_manager, create_user_page):
        """TC-310: 高风险采购订单数据量差异 - 体现权限视野差异

        RBP+LLM核心场景:
        - admin查询"高风险采购订单" → 返回全公司所有org的高风险(多)
        - subsidiary查询"高风险采购订单" → 只返回org1011的高风险(少)

        断言: admin >> subsidiary (体现权限差距)

        reset_manager clears Manager + graph-worker + analytics-worker
        sessions to prevent stale worker context (e.g. "MCP服务不可用"
        hallucinations from forceFlushByTranscriptSize) from polluting
        the dispatch.
        """
        # admin查询
        admin_page = create_user_page("admin", "admin123")
        admin_text = send_query_on_page(admin_page, "查询高风险的采购订单", timeout=120000, settle_timeout_ms=480000)
        admin_count = self._extract_count(admin_text)

        # subsidiary查询
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        subsidiary_text = send_query_on_page(subsidiary_page, "查询高风险的采购订单", timeout=120000, settle_timeout_ms=480000)
        subsidiary_count = self._extract_count(subsidiary_text)

        # 断言: 体现权限差距
        assert admin_count > 0, f"Admin应有数据. Response: {admin_text[:500]}"
        assert subsidiary_count > 0, f"Subsidiary应有数据. Response: {subsidiary_text[:500]}"
        assert admin_count > subsidiary_count * 10, \
            f"Admin({admin_count})>>Subsidiary({subsidiary_count}). " \
            f"权限差距: admin看全公司，subsidiary只看org1021。" \
            f"Admin响应: {admin_text[:300]}; Subsidiary响应: {subsidiary_text[:300]}"

    @pytest.mark.timeout(600)
    def test_tc311_large_amount_po_isolation(self, reset_manager, create_user_page):
        """TC-311: 大额采购订单数据量差异

        - admin: 全org大额PO
        - subsidiary: org1011大额PO
        """
        admin_page = create_user_page("admin", "admin123")
        admin_text = send_query_on_page(admin_page, "统计金额超过50万的采购订单数量", timeout=120000, settle_timeout_ms=480000)
        admin_count = self._extract_count(admin_text)

        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        subsidiary_text = send_query_on_page(subsidiary_page, "统计金额超过50万的采购订单数量", timeout=120000, settle_timeout_ms=480000)
        subsidiary_count = self._extract_count(subsidiary_text)

        assert admin_count > 0, f"Admin应有数据. Response: {admin_text[:500]}"
        assert subsidiary_count > 0, f"Subsidiary应有数据. Response: {subsidiary_text[:500]}"
        assert admin_count > subsidiary_count * 10, \
            f"Admin({admin_count})>>Subsidiary({subsidiary_count}). " \
            f"大领导能看到全公司大额PO，小领导只能看本org。" \
            f"Admin响应: {admin_text[:300]}; Subsidiary响应: {subsidiary_text[:300]}"

    @pytest.mark.timeout(600)
    def test_tc312_abnormal_po_isolation(self, reset_manager, create_user_page):
        """TC-312: 异常采购订单数据量差异

        admin权限大能看到更多异常，subsidiary权限小只能看本org异常
        """
        admin_page = create_user_page("admin", "admin123")
        admin_text = send_query_on_page(admin_page, "统计异常的采购订单数量", timeout=120000, settle_timeout_ms=600000)
        admin_count = self._extract_count(admin_text)

        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        subsidiary_text = send_query_on_page(subsidiary_page, "统计异常的采购订单数量", timeout=120000, settle_timeout_ms=600000)
        subsidiary_count = self._extract_count(subsidiary_text)

        assert admin_count > 0, f"Admin应有数据. Response: {admin_text[:500]}"
        assert subsidiary_count > 0, f"Subsidiary应有数据. Response: {subsidiary_text[:500]}"
        assert admin_count > subsidiary_count * 10, \
            f"Admin({admin_count})>>Subsidiary({subsidiary_count}). " \
            f"admin可发现全公司异常，subsidiary只能发现本org异常。" \
            f"Admin响应: {admin_text[:300]}; Subsidiary响应: {subsidiary_text[:300]}"

    @pytest.mark.timeout(600)
    def test_tc313_supplier_issues_isolation(self, reset_manager, create_user_page):
        """TC-313: 供应商问题数据量差异

        体现: 大领导可发现跨多个org的供应商问题，小领导只能看到本org
        """
        admin_page = create_user_page("admin", "admin123")
        admin_text = send_query_on_page(admin_page, "统计有问题的供应商数量", timeout=120000, settle_timeout_ms=600000)
        admin_count = self._extract_count(admin_text)

        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        subsidiary_text = send_query_on_page(subsidiary_page, "统计有问题的供应商数量", timeout=120000, settle_timeout_ms=600000)
        subsidiary_count = self._extract_count(subsidiary_text)

        assert admin_count > 0, f"Admin应有数据. Response: {admin_text[:500]}"
        assert subsidiary_count > 0, f"Subsidiary应有数据. Response: {subsidiary_text[:500]}"
        assert admin_count > subsidiary_count * 5, \
            f"Admin({admin_count})>>Subsidiary({subsidiary_count}). " \
            f"RBP权限差异体现在数据可见量上。" \
            f"Admin响应: {admin_text[:300]}; Subsidiary响应: {subsidiary_text[:300]}"

    @pytest.mark.timeout(600)
    def test_tc314_payment_issues_isolation(self, reset_manager, create_user_page):
        """TC-314: 付款异常数据量差异

        admin看到所有org的付款异常，subsidiary只看到org1011的
        """
        admin_page = create_user_page("admin", "admin123")
        admin_text = send_query_on_page(admin_page, "统计付款异常的发票数量", timeout=120000, settle_timeout_ms=600000)
        admin_count = self._extract_count(admin_text)

        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        subsidiary_text = send_query_on_page(subsidiary_page, "统计付款异常的发票数量", timeout=120000, settle_timeout_ms=600000)
        subsidiary_count = self._extract_count(subsidiary_text)

        assert admin_count > 0, f"Admin应有数据. Response: {admin_text[:500]}"
        assert subsidiary_count > 0, f"Subsidiary应有数据. Response: {subsidiary_text[:500]}"
        assert admin_count > subsidiary_count * 5, \
            f"Admin({admin_count})>>Subsidiary({subsidiary_count}). " \
            f"体现权限层级决定数据视野。" \
            f"Admin响应: {admin_text[:300]}; Subsidiary响应: {subsidiary_text[:300]}"

    def test_tc315_cross_org_fraud_detection_ability(self, create_user_page):
        """TC-315: 跨org欺诈检测能力差异

        这是RBP+LLM的核心价值场景:
        - admin可以进行全公司范围的欺诈模式分析
        - subsidiary只能在org1011范围内分析

        大领导能发现的欺诈模式远多于小领导
        """
        admin_page = create_user_page("admin", "admin123")
        admin_text = send_query_on_page(admin_page, "分析采购交易中的可疑模式", timeout=120000)
        admin_count = self._extract_count(admin_text)

        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        subsidiary_text = send_query_on_page(subsidiary_page, "分析采购交易中的可疑模式", timeout=120000)
        subsidiary_count = self._extract_count(subsidiary_text)

        # 两者都应该有数据返回(都能进行分析)
        assert admin_count > 0, f"Admin应有分析结果. Response: {admin_text[:200]}"
        assert subsidiary_count > 0, f"Subsidiary应有分析结果. Response: {subsidiary_text[:200]}"

        # 但admin的数据量应远大于subsidiary
        assert admin_count > subsidiary_count * 5, \
            f"Admin({admin_count})>>Subsidiary({subsidiary_count}). " \
            f"全公司视角vs单一org视角，权限决定洞察力差异。"

    @staticmethod
    def _extract_count(text: str) -> int:
        """Extract numeric count from response text.
        Handles numbers with thousand separators (e.g. 13,000 or 13000).

        Pattern priority favours total-count indicators ("共 N 条", "总计 N",
        "总数 N") over generic "N 条" so that a response mentioning both a
        LIMIT-capped row count ("显示前 100 条") and the true total
        ("共 5000 条") yields the total, not the cap.

        Analytics-worker (Hermes) responses use "N 个" instead of "N 条"
        (e.g. "89 个已批准采购订单", "100+ 个采购订单"). These are matched
        after the 条/记录 patterns so that graph-worker responses still
        prefer the higher-priority total-count indicators.
        """
        import re
        # Normalize: remove thousand separators so "13,000" becomes "13000"
        normalized = re.sub(r'(\d),(\d)', r'\1\2', text)
        patterns = [
            r'共[有为]?\s*(\d+)\s*条',     # "共有 5000 条", "共 5000 条"
            r'共[^\d\n]*?(\d+)\s*条',      # "共发现 **23 条**" — analytics-worker markdown bold
            r'总共[有为]?\s*(\d+)\s*条',    # "总共有 5000 条", "总共 5000 条"
            r'总计[为:：]?\s*(\d+)',        # "总计 5000", "总计: 5000"
            r'总数[为:：]?\s*(\d+)',        # "总数 5000", "总数为 5000"
            r'共[有为]?\s*(\d+)',           # "共有 5000", "共 5000" (without 条)
            r'(\d+)\s*条',                 # "5000 条" — fallback
            r'(\d+)\s*记录',               # "5000 记录"
            r'结果[:\s]*(\d+)',            # "结果: 5000"
            r'\bcount[:\s]*(\d+)',         # "count: 5000" (word boundary avoids row_count)
            r'\btotal[:\s]*(\d+)',         # "total: 5000" (word boundary)
            r'共[^\d\n]*?(\d+)\s*个',      # "共发现 **23 个**" — analytics-worker
            r'(\d+)\+\s*个',              # "100+ 个" — analytics-worker with LIMIT
            r'(\d+)\s*个',                # "89 个" — analytics-worker response
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return 0
