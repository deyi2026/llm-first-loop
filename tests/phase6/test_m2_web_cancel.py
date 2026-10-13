"""Phase6 M2：web client 协作取消钩子（设计 §3B，无真机浏览器单测）。

- W1 deepseek 页面等待循环：cancelled 事件 → 早退 DeepSeekPageCancelledError
  + best-effort 停止按钮释放（fake page 记录点击）。
- W2 deepseek 页面 transport：cancel() 置位的事件即传给 adapter 等待的
  同一对象；事件置位后 exchange 即刻以取消结束。
- W3 deepseek client 全链：_ThreadBound/_SurfaceOwned/页面 transport 三层
  委托 + guard 释放（取消后第二次 chat 不阻塞——守卫已随线程退出释放）。
- W4 chatgpt 页面等待循环早退 + client cancel 钩子 fail-open 委托。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from llm_loop.llm.chatgpt_page import (  # noqa: E402
    ChatGPTPageAdapter,
    PageCancelledError,
)
from llm_loop.llm.chatgpt_page import (
    GenerationState as CGGenerationState,
)
from llm_loop.llm.chatgpt_web import ChatGPTWebModelClient  # noqa: E402
from llm_loop.llm.deepseek_page import (  # noqa: E402
    DeepSeekPageAdapter,
    DeepSeekPageCancelledError,
)
from llm_loop.llm.deepseek_protocol import MODEL_PROTOCOL  # noqa: E402
from llm_loop.llm.deepseek_transport import DeepSeekWebPageTransport  # noqa: E402
from llm_loop.llm.deepseek_web import (  # noqa: E402
    DeepSeekWebModelClient,
    _ThreadBoundTransport,
)


class _FakeLocator:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    def count(self) -> int:
        return 1 if self._page.stop_button_visible else 0

    def nth(self, _index: int) -> _FakeLocator:
        return self

    def is_visible(self) -> bool:
        return self._page.stop_button_visible

    def click(self) -> None:
        self._page.stop_clicks.append(time.monotonic())


class _FakeByRoleLocator(_FakeLocator):
    pass


class _FakePage:
    def __init__(self) -> None:
        self.stop_button_visible = False
        self.stop_clicks: list[float] = []
        self.url = "https://chat.deepseek.com/a/some-conversation"

    def wait_for_timeout(self, ms: float) -> None:
        time.sleep(float(ms) / 1000.0)

    def locator(self, _selector: str) -> _FakeLocator:
        return _FakeLocator(self)

    def get_by_role(self, _role: str, *, name: str = "") -> _FakeByRoleLocator:
        return _FakeByRoleLocator(self)


class _NeverSettlesDeepSeekAdapter(DeepSeekPageAdapter):
    """真实等待循环 + DOM 观察桩：永不出现合格终态 → 只有取消能结束。"""

    def __init__(self) -> None:  # noqa: D107
        super().__init__(_FakePage(), profile_label="p6-m2")
        self.stop_button_visible = False

    @property
    def page(self) -> _FakePage:  # noqa: D102
        return self._page  # type: ignore[return-value]

    def observe_messages(self) -> list:  # noqa: D102
        return []

    def _generation_settled(self) -> bool:  # noqa: D102
        return False


class _NeverSettlesChatGPTAdapter(ChatGPTPageAdapter):
    def __init__(self) -> None:  # noqa: D107
        super().__init__(_FakePage(), profile_label="p6-m2")

    @property
    def page(self) -> _FakePage:
        return self._page  # type: ignore[return-value]

    def observe_generation(self) -> CGGenerationState:
        return CGGenerationState(
            streaming=True,
            stop_button_count=1 if self.page.stop_button_visible else 0,
            user_count=1,
            assistant_count=0,
            latest_assistant_identity=None,
            latest_assistant_text=None,
        )

    def observe_messages(self) -> list:  # noqa: D102
        return []


def test_w1_deepseek_wait_loop_cancels_early():
    adapter = _NeverSettlesDeepSeekAdapter()
    adapter.page.stop_button_visible = True  # 生成期停止按钮可见 → 释放点击应发生
    cancelled = threading.Event()
    threading.Timer(0.4, cancelled.set).start()
    t0 = time.monotonic()
    try:
        adapter.wait_for_assistant_completion(
            0, timeout_s=30.0, poll_ms=100, cancelled=cancelled
        )
        raise AssertionError("应在取消时早退")
    except DeepSeekPageCancelledError:
        pass
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, f"取消早退应远小于 timeout（实测 {elapsed:.2f}s）"
    assert adapter.page.stop_clicks, "取消时应 best-effort 点击停止按钮释放页面"


def test_w2_transport_cancel_event_reaches_adapter():
    seen: dict[str, threading.Event | None] = {"event": None}

    class _AdapterStub(_NeverSettlesDeepSeekAdapter):
        def require_binding(self, binding):  # noqa: ANN001
            return None

        def send_text(self, text, *, timeout_s=30.0, confirm_timeout_s=None,
                      poll_ms=100, confirm_token=None, cancelled=None):  # noqa: ANN001
            class _R:
                user_message_identity = "u1"
                conversation_id = "c1"
            return _R()

        def wait_for_assistant_completion(self, before_count, **kwargs):  # noqa: ANN001
            seen["event"] = kwargs.get("cancelled")
            ev = kwargs.get("cancelled")
            assert ev is not None
            ev.wait(timeout=10.0)
            raise DeepSeekPageCancelledError("stub cancelled")

        def observe_generation(self):  # noqa: ANN201, D102
            class _G:
                assistant_count = 0
                latest_assistant_identity = None
            return _G()

        def observe_identity(self):  # noqa: ANN201
            class _B:
                profile_label = "p6-m2"
                url = self._page.url
                title = "t"
                project_ref = None
                conversation_id = "c1"
            return _B()

        def require_no_smart_search(self):
            return None

        def observe_latest_code_blocks(self):
            return []

    transport = DeepSeekWebPageTransport(
        _AdapterStub(), turn_timeout_s=30.0, poll_ms=100
    )
    result: dict[str, object] = {}

    def _run():
        try:
            transport.exchange({"protocol": MODEL_PROTOCOL, "messages": []})
        except DeepSeekPageCancelledError as exc:
            result["cancelled"] = True
            result["msg"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            result["other"] = repr(exc)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    deadline = time.monotonic() + 5.0
    while seen["event"] is None and time.monotonic() < deadline:
        if "other" in result:
            raise AssertionError(f"exchange 前置失败: {result['other']}")
        time.sleep(0.02)
    assert seen["event"] is not None, "adapter 应收到取消事件对象"
    t0 = time.monotonic()
    transport.cancel()
    worker.join(timeout=5.0)
    elapsed = time.monotonic() - t0
    assert result.get("cancelled") is True, result
    assert elapsed < 3.0, f"cancel 后 exchange 应即刻结束（实测 {elapsed:.2f}s）"


class _CancellablePageTransport:
    """页面 transport 桩：exchange 阻塞至 cancel 事件（模拟真实早退）。"""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self.mode = "block"

    def cancel(self) -> None:
        self._cancelled.set()

    def exchange(self, request, *, timeout_s=None):  # noqa: ANN001
        if self.mode == "block":
            self._cancelled.wait(timeout=20.0)
            raise DeepSeekPageCancelledError("page transport cancelled")
        raise ValueError("second-call-probe")


def test_w3_client_chain_and_guard_release():
    page_transport = _CancellablePageTransport()
    thread_bound = _ThreadBoundTransport(lambda: page_transport)
    client = DeepSeekWebModelClient(thread_bound)
    outcome: dict[str, object] = {}

    def _first_chat():
        try:
            client.chat([{"role": "user", "content": "hi"}], [])
        except DeepSeekPageCancelledError:
            outcome["first"] = "cancelled"
        except Exception as exc:  # noqa: BLE001
            outcome["first"] = f"other:{exc!r}"

    worker = threading.Thread(target=_first_chat, daemon=True)
    worker.start()
    time.sleep(0.5)
    assert worker.is_alive(), "chat 应阻塞在页面等待上"
    t0 = time.monotonic()
    client.cancel()
    worker.join(timeout=5.0)
    first_elapsed = time.monotonic() - t0
    assert outcome.get("first") == "cancelled", outcome
    assert first_elapsed < 3.0, f"cancel 后 chat 应即刻结束（实测 {first_elapsed:.2f}s）"
    # guard 已释放：第二次调用不被阻塞（以不同异常即刻返回证明守卫空闲）
    page_transport.mode = "probe"
    t1 = time.monotonic()
    try:
        client.chat([{"role": "user", "content": "again"}], [])
        raise AssertionError("probe 模式应抛 ValueError")
    except ValueError:
        pass
    assert time.monotonic() - t1 < 3.0, "guard 应已释放，第二次 chat 不应阻塞"


def test_w4_chatgpt_wait_loop_and_client_hook():
    adapter = _NeverSettlesChatGPTAdapter()
    adapter.page.stop_button_visible = True
    cancelled = threading.Event()
    threading.Timer(0.4, cancelled.set).start()
    t0 = time.monotonic()
    try:
        adapter.wait_for_assistant_completion(
            0, timeout_s=30.0, poll_ms=100, cancelled=cancelled
        )
        raise AssertionError("应在取消时早退")
    except PageCancelledError:
        pass
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, f"取消早退应远小于 timeout（实测 {elapsed:.2f}s）"

    class _Hooked:
        def __init__(self) -> None:
            self.cancelled = 0
            self.exchange = None  # 不被调用

        def cancel(self) -> None:
            self.cancelled += 1

    hooked = _Hooked()
    client = ChatGPTWebModelClient(hooked)  # type: ignore[arg-type]
    client.cancel()
    assert hooked.cancelled == 1, "client.cancel 应 fail-open 委托到 transport.cancel"
