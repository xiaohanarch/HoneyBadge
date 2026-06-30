"""Debug TC105: capture page state during query."""
import json

from playwright.sync_api import Page


def test_debug_tc105(admin_logged_in: Page, wait_for_chat_ready):
    page = admin_logged_in
    wait_for_chat_ready()

    matrix_events = []
    page.on("console", lambda m: matrix_events.append(f"[{m.type}] {m.text[:300]}"))
    page.on("pageerror", lambda e: matrix_events.append(f"[PAGEERROR] {e}"))
    page.on("response", lambda r: matrix_events.append(f"[RESP {r.status}] {r.url[:120]}") if "_matrix" in r.url and "sync" not in r.url else None)

    textarea = page.locator(".input-container .el-textarea__inner").first
    textarea.fill("\u67e5\u8be2\u524d5\u4e2a\u91c7\u8d2d\u8ba2\u5355")
    textarea.press("Enter")

    # Wait 90s for response
    page.wait_for_timeout(90000)

    # Inspect chat messages
    state = page.evaluate("""() => {
        const msgs = document.querySelectorAll('.chat-message');
        const result = [];
        msgs.forEach((m, i) => {
            const body = m.querySelector('.message-body') || m;
            result.push({
                idx: i,
                role: m.className,
                text: (body.textContent || '').slice(0, 300),
            });
        });
        return result;
    }""")

    print("\n=== Chat messages on page ===")
    for m in state:
        print(json.dumps(m, ensure_ascii=False))

    # Get pinia store state
    pinia_state = page.evaluate("""() => {
        try {
            const app = document.querySelector('#app').__vue_app__;
            const store = app.config.globalProperties.$pinia._s.get('chat');
            return {
                loading: store.loading,
                error: store.error,
                msgCount: store.currentMessages.length,
                lastMsg: store.currentMessages[store.currentMessages.length-1],
            };
        } catch (e) {
            return {err: String(e)};
        }
    }""")
    print("\n=== Pinia chat store ===")
    print(json.dumps(pinia_state, ensure_ascii=False, default=str))

    print("\n=== Console events (last 60) ===")
    for ev in matrix_events[-60:]:
        print(ev)
