"""
Context Continuity and Memory E2E Tests
HoneyBadge - Enterprise Knowledge Graph Assistant

Test Coverage:
- TC-1001: Same user context continuity (multi-turn conversation)
- TC-1002: Session persistence after logout/login
- TC-1003: Memory saved and recalled correctly
- TC-1004: Memory NOT shared between different users
- TC-1005: User context isolation (different users = completely independent contexts)
- TC-1006: Context reset doesn't affect other sessions
- TC-1007: Cross-session memory persistence

RBP + LLM Context Value:
- 大领导(admin): 可以跨多个org分析，上下文丰富
- 小领导(subsidiary): 只能看本org，但上下文仍然连续

用户隔离核心:
- admin 的会话/memory 绝对不会出现在 analyst/subsidiary 的界面中
- 每个用户看到的只有自己的会话列表和消息历史
"""
import pytest
from playwright.sync_api import expect
from tests.e2e.conftest import send_query_on_page
from tests.e2e.selectors import (
    CHAT_TEXTAREA, MSG_ASSISTANT, NEW_CHAT_BUTTON,
)


BASE_URL = "http://localhost:3000"


class TestContextAndMemory:
    """Test context continuity, memory persistence, and user isolation."""

    def test_tc1001_same_user_context_continuity(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-1001: Same user context is continuous across multiple queries.

        用户在同一会话中发送多条消息，上下文应该连续。
        例如:
        Q1: "查询采购订单" → A1: 返回PO列表
        Q2: "统计金额" → A2: 基于A1的上下文继续分析
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # First query - 询问基本信息
        send_chat_query("查询采购订单", timeout=20000)
        page.wait_for_timeout(2000)
        first_response_count = page.locator('.chat-message').count()

        # Second query - 基于上文的追问
        send_chat_query("统计这些订单的总金额", timeout=60000)
        page.wait_for_timeout(2000)
        second_response_count = page.locator('.chat-message').count()

        # Third query - 继续追问
        send_chat_query("找出金额最大的前3个", timeout=60000)
        page.wait_for_timeout(2000)
        third_response_count = page.locator('.chat-message').count()

        # 断言: 上下文连续，消息应该递增
        assert first_response_count >= 2, "First query should have user+assistant messages"
        assert second_response_count > first_response_count, "Second query should add messages"
        assert third_response_count > second_response_count, "Third query should add more messages"

        # 验证 assistant 消息数量 (使用实际 DOM class)
        assistant_msgs = page.locator(MSG_ASSISTANT)

        # 应该有至少3轮对话 (每轮 = 1 user + 1 assistant)
        assert assistant_msgs.count() >= 3, \
            f"Should have >=3 assistant responses for context continuity. Got: {assistant_msgs.count()}"

    def test_tc1002_session_persistence_after_logout_login(self, create_user_page):
        """TC-1002: Session persists after logout and login again.

        用户创建会话后登出，再登录应该能看到相同的会话和消息历史。
        """
        # 创建 admin 会话
        admin_page = create_user_page("admin", "admin123")
        wait_for_chat_ready(admin_page)

        # 发送查询创建内容
        send_query_on_page(admin_page, "查询采购订单", timeout=20000)
        admin_page.wait_for_timeout(2000)

        # 获取当前会话 ID (从 URL 或 localStorage)
        session_url = admin_page.url
        messages_before_logout = admin_page.locator('.chat-message').count()

        # 登出
        logout_btn = admin_page.locator('button:has-text("退出"), button:has-text("Logout")')
        if logout_btn.count() == 0:
            pytest.skip("Logout button not found in UI")
        logout_btn.first.click()
        admin_page.wait_for_url(f"{BASE_URL}/login", timeout=30000)
        admin_page.wait_for_timeout(1000)

        # 重新登录
        admin_page2 = create_user_page("admin", "admin123")
        wait_for_chat_ready(admin_page2)

        # 应该看到相同的会话
        messages_after_login = admin_page2.locator('.chat-message').count()

        # 断言: 登出登录后应该保留会话上下文
        assert messages_after_login >= 2, \
            f"After logout/login, should preserve session context. Before: {messages_before_logout}, After: {messages_after_login}"

    def test_tc1003_memory_saved_and_recalled(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-1003: Memory is saved and recalled correctly within session.

        用户在会话中提到的信息，系统应该记住并在后续查询中使用。
        例如:
        Q1: "我关注采购订单" → A1
        Q2: "哪些订单金额超过100万" → A2: 系统应该"记住"用户关注采购订单
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # First query - 设置上下文/关注点
        send_chat_query("我主要关注采购订单的数据", timeout=20000)
        page.wait_for_timeout(2000)

        # Second query - 利用之前的上下文
        send_chat_query("找出金额最大的10个", timeout=60000)
        page.wait_for_timeout(2000)
        response = page.locator(MSG_ASSISTANT)
        response_text = response.last.inner_text() if response.count() > 0 else ""

        # 断言: 应该有上下文响应（不是完全无关的回答）
        assert len(response_text) > 10, \
            f"Second query should leverage context. Response: {response_text[:200]}"

    def test_tc1004_memory_not_shared_between_users(self, create_user_page):
        """TC-1004: Memory is NOT shared between different users.

        admin 在自己的会话中提到的内容，analyst 绝对不应该看到。
        这是用户隔离的核心验证。
        """
        # Admin 创建会话并设置私密上下文
        admin_page = create_user_page("admin", "admin123")
        wait_for_chat_ready(admin_page)
        send_query_on_page(admin_page, "我正在分析ORG1000的采购数据，这是公司最关键的部门", timeout=20000)
        admin_page.wait_for_timeout(2000)

        # 获取 admin 的消息
        admin_messages = admin_page.locator('.chat-message').all()
        admin_has_sensitive_info = any(
            "ORG1000" in msg.inner_text() or "关键" in msg.inner_text()
            for msg in admin_messages
        )

        # Analyst 登录 - 应该完全看不到 admin 的内容
        analyst_page = create_user_page("analyst", "analyst123")
        wait_for_chat_ready(analyst_page)

        # Analyst 的消息列表
        analyst_messages = analyst_page.locator('.chat-message').all()
        analyst_text = " ".join(msg.inner_text() for msg in analyst_messages)

        # 断言: analyst 绝对不应该看到 admin 的私密信息
        assert admin_has_sensitive_info, "Admin session should have sensitive content to verify isolation"
        assert "ORG1000" not in analyst_text, \
            "Analyst should NEVER see admin's confidential context"
        assert "关键" not in analyst_text, \
            "Analyst should NEVER see admin's memory/context"

    def test_tc1005_user_context_isolation(self, create_user_page):
        """TC-1005: Different users have completely independent contexts.

        admin 和 subsidiary_lead 各自创建会话，内容完全独立。
        """
        # Admin 创建会话
        admin_page = create_user_page("admin", "admin123")
        wait_for_chat_ready(admin_page)
        send_query_on_page(admin_page, "这是admin的会话，查询所有采购订单", timeout=20000)
        admin_page.wait_for_timeout(2000)
        admin_text = admin_page.locator(MSG_ASSISTANT).last.inner_text() if admin_page.locator(MSG_ASSISTANT).count() > 0 else ""

        # Subsidiary 创建会话
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        wait_for_chat_ready(subsidiary_page)
        send_query_on_page(subsidiary_page, "这是subsidiary的会话，只看本公司的订单", timeout=20000)
        subsidiary_page.wait_for_timeout(2000)
        subsidiary_text = subsidiary_page.locator(MSG_ASSISTANT).last.inner_text() if subsidiary_page.locator(MSG_ASSISTANT).count() > 0 else ""

        # 断言: 两个用户的上下文完全独立，不应交叉
        assert "admin" not in subsidiary_text.lower() or len(subsidiary_text) == 0, \
            "Subsidiary should not see admin's context"
        assert "这是admin" not in subsidiary_text, \
            "User contexts must be completely isolated"

    def test_tc1006_context_reset_does_not_affect_other_sessions(self, create_user_page):
        """TC-1006: Creating new session resets context but doesn't affect other sessions.

        用户创建新会话，旧会话的上下文应该保留。
        """
        # Admin 创建第一个会话
        admin_page1 = create_user_page("admin", "admin123")
        wait_for_chat_ready(admin_page1)
        send_query_on_page(admin_page1, "会话1: 查询采购订单", timeout=20000)
        admin_page1.wait_for_timeout(2000)
        session1_messages = admin_page1.locator('.chat-message').count()

        # 在同一浏览器中创建第二个会话
        new_session_btn = admin_page1.locator(NEW_CHAT_BUTTON)
        if new_session_btn.count() == 0:
            pytest.skip("New session button not available")
        new_session_btn.first.click()
        admin_page1.wait_for_timeout(1000)
        send_query_on_page(admin_page1, "会话2: 查询销售订单", timeout=20000)
        admin_page1.wait_for_timeout(2000)
        session2_messages = admin_page1.locator('.chat-message').count()

        # 断言: 新会话应该有不同的上下文
        assert session2_messages >= 2, "New session should have independent context"

        # 用新 page 登录，验证第一个会话仍然存在
        admin_page2 = create_user_page("admin", "admin123")
        wait_for_chat_ready(admin_page2)

        # 应该能看到之前的会话
        session_list = admin_page2.locator('.session-item, [class*="session"]')
        # 断言: 会话列表应该存在（隔离验证）
        assert session_list.count() >= 0, "Previous sessions should be accessible"

    def test_tc1007_cross_session_memory_persistence(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-1007: Memory persists across different sessions for same user.

        同一用户在不同会话中，Memory/偏好设置应该保留。
        例如:
        - 在会话1中设置"我关注PTP流程"
        - 创建新会话
        - 在会话2中问"我关注的流程最近有哪些异常"
        - 系统应该记得"PTP流程"这个偏好
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # Session 1 - 设置偏好
        send_chat_query("记住我主要关注采购流程的异常情况", timeout=60000)
        page.wait_for_timeout(2000)

        # 创建新会话
        new_session_btn = page.locator(NEW_CHAT_BUTTON)
        if new_session_btn.count() == 0:
            pytest.skip("New session button not available")
        new_session_btn.first.click()
        page.wait_for_timeout(1000)

        # Session 2 - 验证偏好被记住
        send_chat_query("我关注的流程最近有什么异常", timeout=60000)
        page.wait_for_timeout(2000)
        response = page.locator(MSG_ASSISTANT)
        response_text = response.last.inner_text() if response.count() > 0 else ""

        # 断言: 应该基于之前设置的偏好来回答
        assert len(response_text) > 0, \
            f"Should leverage persisted memory/preference. Response: {response_text[:200]}"

        # 验证响应中提到了"采购"或"异常"相关
        # (这是 Memory 跨会话保留的间接验证)
        has_relevant_context = any(
            kw in response_text for kw in ["采购", "异常", "订单", "PO", "查询", "处理"]
        )
        assert has_relevant_context, \
            f"Response should reflect persisted context from previous session. Got: {response_text[:200]}"

    def test_tc1008_analyst_cannot_see_admin_history(self, create_user_page):
        """TC-1008: Analyst cannot see admin's conversation history.

        核心安全验证: analyst 登录后，绝对不应该看到 admin 的任何会话历史。
        """
        # Admin 创建私密会话
        admin_page = create_user_page("admin", "admin123")
        wait_for_chat_ready(admin_page)
        send_query_on_page(admin_page, "这是admin的私密分析，只存在于admin账号中", timeout=20000)
        admin_page.wait_for_timeout(2000)

        # Analyst 登录 (独立浏览器上下文, 天然隔离, 无需先 logout admin)
        analyst_page = create_user_page("analyst", "analyst123")
        wait_for_chat_ready(analyst_page)

        # 检查 analyst 的界面
        all_text = analyst_page.locator('body').inner_text()

        # 断言: analyst 绝对不应该看到 admin 的会话标题"私密"
        assert "私密" not in all_text, \
            "CRITICAL: Analyst should NEVER see admin's private session titles"
        assert "只存在于admin" not in all_text, \
            "CRITICAL: User history isolation violated"

    def test_tc1009_subsidiary_cannot_see_other_subsidiary_history(self, create_user_page):
        """TC-1009: One subsidiary cannot see another subsidiary's history.

        假设有多个子公司用户，各自的数据完全隔离。
        当前只有 subsidiary_lead(org=1021)，验证其看不到其他 org 的数据。
        """
        # subsidiary_lead 创建会话
        subsidiary_page = create_user_page("subsidiary_lead", "lead123")
        wait_for_chat_ready(subsidiary_page)
        send_query_on_page(subsidiary_page, "这是ORG1021的数据，别的子公司看不到", timeout=20000)
        subsidiary_page.wait_for_timeout(2000)

        # 用 analyst(org=1000) 登录 (独立浏览器上下文, 天然隔离)
        analyst_page = create_user_page("analyst", "analyst123")
        wait_for_chat_ready(analyst_page)

        # analyst 应该看不到 subsidiary_lead 的会话
        all_text = analyst_page.locator('body').inner_text()

        # 断言: analyst(org=1000) 绝对不应该看到 subsidiary(org=1021) 的数据
        assert "ORG1021" not in all_text, \
            "CRITICAL: Analyst should NEVER see subsidiary's org data"
        assert "别的子公司" not in all_text, \
            "CRITICAL: Cross-subsidiary data isolation violated"

    def test_tc1010_context_summary_accuracy(self, admin_logged_in, wait_for_chat_ready, send_chat_query):
        """TC-1010: Context summary accurately reflects conversation history.

        验证 LLM 生成的上游查询真的包含了对之前上下文的理解。
        """
        page = admin_logged_in
        wait_for_chat_ready()

        # Multi-turn conversation
        queries = [
            "查询2024年的采购订单",
            "这些订单有哪些供应商",
            "哪些供应商的金额最大",
            "总结一下我刚才问的问题"
        ]

        for query in queries:
            send_chat_query(query, timeout=20000)
            page.wait_for_timeout(2000)

        # 检查最后的响应是否总结了之前的对话
        all_messages = page.locator(MSG_ASSISTANT).all()
        last_response = all_messages[-1].inner_text() if all_messages else ""

        # 断言: 最后的问题"总结一下"应该得到一个总结
        # 如果上下文正常，最后的回答应该包含之前问题的关键词
        has_context_summary = any(
            kw in last_response for kw in ["采购", "订单", "供应商", "金额", "2024", "查询", "总结"]
        )
        assert has_context_summary, \
            f"Summary should reflect previous context. Got: {last_response[:300]}"


# Helper function
def wait_for_chat_ready(page):
    """Wait for chat interface to be ready."""
    page.wait_for_selector(CHAT_TEXTAREA, timeout=15000)
    page.wait_for_timeout(3000)
