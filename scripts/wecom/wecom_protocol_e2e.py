"""企微桥协议层端到端验证（不联网、不需凭据）。

构造真实格式的企微回调帧，走 dispatcher → WeComMessageHandler → 假引擎 → 回复，
验证 M0 核心目标「企微发一句话，LFL 回一句话」在协议层成立。

用法：PYTHONPATH=<repo>/src .venv/bin/python scripts/wecom/wecom_protocol_e2e.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.core.session import SessionStore  # noqa: E402
from llm_loop.wecom.dispatcher import parse_message_frame  # noqa: E402
from llm_loop.wecom.handlers import WeComMessageHandler  # noqa: E402
from llm_loop.wecom.session_map import WeComSessionMap  # noqa: E402


class _Result:
    def __init__(self, text: str) -> None:
        self.final_answer = text
        self.truncated = False
        self.provider_output_truncated = False
        self.verification_note = None


class FakeEngine:
    """最小假引擎：run(sid, text, user_metadata=...) -> 结果对象。"""

    def __init__(self, text: str = "收到，我是 LFL。") -> None:
        self._text = text
        self.calls: list[tuple[str, str]] = []

    def run(self, sid, text, **_kw):
        self.calls.append((sid, text))
        return _Result(self._text)


def _text_frame(req_id: str, content: str, *, userid: str = "u_demo") -> dict:
    return {
        "cmd": "aibot_callback",
        "headers": {"req_id": req_id},
        "body": {
            "msgtype": "text",
            "from": {"userid": userid, "sender_type": "user"},
            "chatid": "",
            "chat_type": "single",
            "text": {"content": content},
        },
    }


def _video_frame(req_id: str) -> dict:
    return {
        "cmd": "aibot_callback",
        "headers": {"req_id": req_id},
        "body": {
            "msgtype": "video",
            "from": {"userid": "u_demo", "sender_type": "user"},
            "video": {"url": "https://example.invalid/v.mp4", "aeskey": "k"},
        },
    }


def _compat_frame(req_id: str) -> dict:
    frame = _text_frame(req_id, "来自智能助理的消息")
    frame["body"]["compat_info"] = {"source": "ai_assistant"}
    return frame


def main() -> int:
    replies: list[dict] = []

    def fake_reply(req_id, receive_id, text, receive_id_type):
        replies.append({
            "req_id": req_id,
            "receive_id": receive_id,
            "text": text,
            "receive_id_type": receive_id_type,
        })
        return {"errcode": 0}

    tmp = tempfile.mkdtemp(prefix="wecom_e2e_")
    store = SessionStore(Path(tmp) / "sessions")
    smap = WeComSessionMap(store, path=str(Path(tmp) / "map.json"))
    engine = FakeEngine()
    handler = WeComMessageHandler(
        engine=engine,
        session_map=smap,
        reply_fn=fake_reply,
        audit_dir=str(Path(tmp) / "audit"),
    )
    failures: list[str] = []

    # 1) 文本消息：正常回复 + req_id 绑定
    msg = parse_message_frame(_text_frame("REQ-001", "你好"))
    if msg is None:
        failures.append("文本帧解析失败")
    else:
        handler.handle(msg)
        if not replies:
            failures.append("文本消息未产生回复")
        else:
            r = replies[-1]
            if r["req_id"] != "REQ-001":
                failures.append(f"req_id 未透传：期望 REQ-001，实际 {r['req_id']!r}")
            if r["receive_id"] != "u_demo":
                failures.append(f"回复目标 userid 错误：{r['receive_id']!r}")
            if "LFL" not in r["text"]:
                failures.append(f"回复内容不含引擎输出：{r['text']!r}")

    # 2) 同一用户第二轮 → 同一 session（多轮连续）
    msg2 = parse_message_frame(_text_frame("REQ-002", "第二句"))
    if msg2 is not None:
        handler.handle(msg2)
        if len(engine.calls) == 2 and engine.calls[0][0] != engine.calls[1][0]:
            failures.append(f"同一 userid 两轮落到不同 session：{engine.calls}")

    # 3) video 帧：不得静默丢弃（SDK 会丢，这里必须显式回执）
    before = len(replies)
    vmsg = parse_message_frame(_video_frame("REQ-003"))
    if vmsg is None:
        failures.append("video 帧被丢弃（应被解析）")
    elif vmsg.msg_type != "video":
        failures.append(f"video 帧 msg_type 错误：{vmsg.msg_type!r}")
    else:
        handler.handle(vmsg)
        if len(replies) <= before:
            failures.append("video 消息未显式回执（静默丢弃）")

    # 4) compat_info 帧：必须跳过
    before = len(replies)
    cmsg = parse_message_frame(_compat_frame("REQ-004"))
    if cmsg is not None:
        failures.append("compat_info 帧未被跳过")
    elif len(replies) != before:
        failures.append("compat_info 帧产生了回复（应跳过）")

    print(f"engine_calls={len(engine.calls)} replies={len(replies)}")
    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("PROTOCOL_E2E_OK: 文本回复/req_id 绑定/多轮同 session/video 不丢/compat_info 跳过 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
