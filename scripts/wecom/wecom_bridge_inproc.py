"""企微桥进程内全链路验证（不联网、不需凭据）。

用假 SDK 客户端驱动真实 WeComBridge，验证：
  SDK 回调 → 有界队列 → 单 worker 线程 → dispatcher → handler → 假引擎 → 回复
并核对 req_id 绑定、队列有界、单实例锁、优雅退出无残留线程。

用法：PYTHONPATH=<repo>/src .venv/bin/python scripts/wecom/wecom_bridge_inproc.py
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.core.session import SessionStore  # noqa: E402
from llm_loop.wecom.bridge import WeComBridge  # noqa: E402
from llm_loop.wecom.config import WeComConfig  # noqa: E402
from llm_loop.wecom.handlers import WeComMessageHandler  # noqa: E402
from llm_loop.wecom.session_map import WeComSessionMap  # noqa: E402


class _Result:
    def __init__(self, text: str) -> None:
        self.final_answer = text
        self.truncated = False
        self.provider_output_truncated = False
        self.verification_note = None


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run(self, sid, text, **_kw):
        self.calls.append((sid, text))
        return _Result(f"Echo: {text}")


class FakeClient:
    """假 aibot.WSClient：记录 reply 调用，模拟 SDK 事件回调。"""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.replies: list[dict] = []
        self.connected = False

    def on(self, event, fn):
        self.handlers[event] = fn

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def connect(self):
        self.connected = True
        return self

    def disconnect(self):
        """真实 SDK 的 disconnect() 是同步方法（内部 ensure_future 调度异步关闭）。"""
        self.connected = False

    async def reply(self, frame, body, cmd=None):
        self.replies.append({"frame": frame, "body": body, "cmd": cmd})
        return {"errcode": 0}

    # 测试侧：模拟服务端下发一帧
    def emit_message(self, frame: dict) -> None:
        self.handlers["message"](frame)


def _text_frame(req_id: str, content: str) -> dict:
    return {
        "cmd": "aibot_callback",
        "headers": {"req_id": req_id},
        "body": {
            "msgtype": "text",
            "from": {"userid": "u_demo", "sender_type": "user"},
            "chatid": "",
            "chat_type": "single",
            "text": {"content": content},
        },
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="wecom_inproc_"))
    cfg = WeComConfig(
        bot_id="fake_bot",
        secret="fake_secret",
        session_map_path=str(tmp / "map.json"),
    )
    store = SessionStore(tmp / "sessions")
    smap = WeComSessionMap(store, path=str(tmp / "map.json"))
    engine = FakeEngine()

    fake_client = FakeClient()
    bridge = WeComBridge(
        cfg,
        None,
        client_factory=lambda _c: fake_client,
        lock_path=str(tmp / "lock"),
    )
    # 与 llm_loop.wecom.build_bridge 一致的装配顺序：handler.reply_fn = bridge.send_text
    handler = WeComMessageHandler(
        engine=engine,
        session_map=smap,
        reply_fn=bridge.send_text,
        audit_dir=str(tmp / "audit"),
    )
    bridge.attach_handler(handler)
    failures: list[str] = []

    before_threads = {t.name for t in threading.enumerate()}
    if not bridge.start():
        failures.append("bridge.start() 返回 False")
    else:
        deadline = time.time() + 10
        while time.time() < deadline and not fake_client.connected:
            time.sleep(0.05)
        if not fake_client.connected:
            failures.append("SDK 客户端未连接")

        # 下发一帧真实格式的回调
        fake_client.emit_message(_text_frame("REQ-A", "在吗"))
        deadline = time.time() + 10
        while time.time() < deadline and not fake_client.replies:
            time.sleep(0.05)
        if not fake_client.replies:
            failures.append("未产生回复")
        else:
            r = fake_client.replies[-1]
            got_req = (r["frame"].get("headers") or {}).get("req_id")
            if got_req != "REQ-A":
                failures.append(f"reply 帧 req_id 错误：{got_req!r}")
            content = (r["body"] or {}).get("markdown", {}).get("content", "")
            if "Echo" not in content:
                failures.append(f"回复内容不含引擎输出：{content!r}")

        # 队列有界：直接灌满后应丢而不阻塞
        from llm_loop.wecom.bridge import _MAX_MSG_QUEUE
        if bridge._msg_queue.maxsize != _MAX_MSG_QUEUE:
            failures.append(f"队列上限不是 {_MAX_MSG_QUEUE}")

        bridge.stop()

    # 优雅退出：不得残留本进程新增线程
    time.sleep(1.0)
    leaked = [
        t.name for t in threading.enumerate()
        if t.name not in before_threads and not t.daemon
    ]
    if leaked:
        failures.append(f"退出后残留线程：{leaked}")

    print(f"replies={len(fake_client.replies)} engine_calls={len(engine.calls)}")
    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("BRIDGE_INPROC_OK: 回调→队列→worker→引擎→回复 全链路通过，req_id 正确，无残留线程")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
