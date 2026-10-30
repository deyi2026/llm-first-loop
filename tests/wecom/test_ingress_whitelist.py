"""企微通道 ingress 凭据测试（P0：白名单固有成员 + handler 签发）.

背景（2026-10-30 用户实测）：wecom 不在 INTRINSIC_CHANNELS 且 handler 未签发
ingress → enforce 模式下 engine.run 的 user 写入被拒，用户收到「[写入被拒]」
回执而非 LFL 回答。本文件锁定两层修复：
1) channel_whitelist/ingress_token 的 wecom 固有成员资格（签发 + 白名单判定）；
2) WeComMessageHandler 走 engine.run 时必须携带 channel="wecom" 的 ingress 凭据。
"""

from __future__ import annotations

from llm_loop.core.trace_leak.channel_whitelist import (
    INTRINSIC_CHANNELS,
    assert_intrinsic_immutable,
    whitelist_allows,
)
from llm_loop.core.trace_leak.ingress_token import (
    IngressToken,
    is_whitelisted,
    issue_ingress,
)
from llm_loop.wecom.handlers import WeComMessageHandler
from llm_loop.wecom.messages import WeComMessage


class FakeResult:
    def __init__(self, final_answer: str) -> None:
        self.final_answer = final_answer
        self.truncated = False
        self.verification_note = ""
        self.provider_output_truncated = False


class IngressCaptureEngine:
    """捕获 engine.run 的 ingress 实参（不跑真实推理，只验凭据链路）."""

    def __init__(self) -> None:
        self.captured: list[object] = []
        self.calls: list[tuple[str, str]] = []
        self.reasoning_modes: list[object] = []

    def run(self, sid: str, text: str, ingress=None, reasoning_mode=None, user_metadata=None):  # noqa: ARG002
        self.captured.append(ingress)
        self.calls.append((sid, text))
        self.reasoning_modes.append(reasoning_mode)
        return FakeResult("ok")


class FakeSessionMap:
    def get_or_create(self, key: str) -> str:  # noqa: ARG002
        return "sid_wecom"


def _text_msg(req_id: str = "req_ingress_1") -> WeComMessage:
    return WeComMessage(
        message_id=f"m_{req_id}",
        sender_id="u_ingress",
        chat_id="",
        chat_type="single",
        msg_type="text",
        text="你好",
        sender_type="user",
        req_id=req_id,
    )


def test_wecom_is_intrinsic_channel() -> None:
    """wecom 已入固有成员且不可移除断言覆盖它（防回归回三元组）."""
    assert "wecom" in INTRINSIC_CHANNELS
    assert_intrinsic_immutable()  # 内含 {"feishu","web","cli","wecom"} <= INTRINSIC


def test_issue_ingress_wecom_is_whitelisted() -> None:
    """issue_ingress("wecom") 可签发（不再抛 ValueError）且白名单判定通过."""
    tok = issue_ingress("wecom")
    assert isinstance(tok, IngressToken)
    assert tok.channel == "wecom"
    assert tok.entry == "wecom"  # 通道级键（entry 缺省=channel，与 feishu 同构）
    assert is_whitelisted(tok) is True
    assert whitelist_allows(tok) is True
    assert issue_ingress("wecom") is tok  # 同 channel 签发幂等


def test_handler_passes_wecom_ingress_to_engine(tmp_path) -> None:
    """handler.handle → engine.run 必须携带 channel="wecom" 的 ingress 凭据.

    这是 2026-10-30 P0 缺陷的第二半：白名单放行但 handler 不签发同样被拒。
    """
    engine = IngressCaptureEngine()
    replies: list[tuple] = []
    handler = WeComMessageHandler(
        engine,
        FakeSessionMap(),
        lambda req_id, rid, text, rtype: replies.append((req_id, rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    handler.handle(_text_msg())
    assert engine.calls == [("sid_wecom", "你好")]
    assert len(engine.captured) == 1
    tok = engine.captured[0]
    assert tok is not None, "engine.run 必须收到 ingress 凭据（None=enforce 必拒）"
    assert getattr(tok, "channel", None) == "wecom"
    assert is_whitelisted(tok) is True
    # 2026-10-30 用户指令「Always_on_effort 改为 on」：请求级 reasoning 模式须为 on
    assert engine.reasoning_modes == ["on"], "企微接入的 reasoning_mode 必须是 on（用户显式指令）"
    # 回复内容是引擎产出（而非「[写入被拒]」拒绝文案）
    assert replies and replies[0][2] == "ok"
