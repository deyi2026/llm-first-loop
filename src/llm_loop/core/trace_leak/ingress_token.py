"""IngressToken 哨兵类型与签发接口（tasks 3.1，design §2.2 组1，spec 5.3.1）.

token 为模块私有哨兵类型实例（非字符串——防字符串拼接伪造）：
进程外不可伪造、进程内仅 ``issue_ingress`` 可构造。

- ``issue_ingress(channel) -> IngressToken``：channel 限 feishu/web/cli
  （白名单固有成员），未知 channel 抛 ValueError——默认拒绝的构造性体现。
- 同 channel 多次签发幂等（返回等价凭据，不产生重复事件）。
- ``issue_test_ingress()``：测试后门显式凭据（spec 5.3.3-4a 测试专用入口
  显式隔离标记），生产代码禁止使用。
"""

from __future__ import annotations

import contextvars
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 类型检查专用，避免运行时循环导入
    pass


class IngressToken:
    """人类输入通道准入凭据（哨兵对象；仅本模块可构造实例）。"""

    __slots__ = ("channel", "entry", "issued_at", "delegated")

    def __init__(self, _pin: object, channel: str, entry: str, *, delegated: bool = False) -> None:
        # _pin 为模块私有哨兵：外部无法伪造该参数 → 无法绕过 issue_ingress 构造
        if _pin is not _ISSUE_PIN:
            raise ValueError("IngressToken 仅可经 issue_ingress 构造（哨兵防护）")
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "issued_at", f"{time.time():.6f}")
        object.__setattr__(self, "delegated", bool(delegated))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("IngressToken 不可变（哨兵凭据）")

    def __repr__(self) -> str:  # pragma: no cover - 调试友好
        suffix = ", delegated=True" if self.delegated else ""
        return f"IngressToken(channel={self.channel!r}, entry={self.entry!r}{suffix})"


class _IssuePin:
    """模块私有哨兵（不导出；防进程内绕过 issue_ingress 直接构造）。"""


_ISSUE_PIN = _IssuePin()

# 通道值域（白名单固有成员，spec 6.2-4）
_ALLOWED_CHANNELS = frozenset({"feishu", "web", "cli"})

_ISSUED: dict[str, IngressToken] = {}

# 当前顶层 run 的真实 ingress 凭据及其绑定 session。schedule(wake=True) 只允许
# 在同一 human run 内把该凭据降权委派一次；子代理改写 current_session_id 后会
# 因 session 不匹配失去授权，scheduled continuation 本身也不能递归再委派。
current_ingress_token: contextvars.ContextVar[IngressToken | None] = contextvars.ContextVar(
    "llm_loop_current_ingress_token", default=None
)
current_ingress_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_loop_current_ingress_session_id", default=""
)


def issue_ingress(channel: str) -> IngressToken:
    """签发人类输入通道凭据；同 channel 幂等（等价凭据，零重复事件）。"""
    ch = str(channel or "")
    if ch not in _ALLOWED_CHANNELS:
        raise ValueError(f"未知 ingress channel: {ch!r}（白名单外通道不存在签发路径，默认拒绝）")
    tok = _ISSUED.get(ch)
    if tok is None:
        tok = IngressToken(_ISSUE_PIN, ch, entry=ch)
        _ISSUED[ch] = tok
    return tok


def issue_test_ingress() -> IngressToken:
    """测试后门显式凭据（entry=test_harness；spec 5.3.3-4a 显式隔离标记）.

    仅供测试代码对齐生产白名单路径；生产代码禁止使用（T2 断言）。
    """
    tok = _ISSUED.get("test_harness")
    if tok is None:
        # channel 落在固有值域外的专用哨兵通道：仅白名单 entries 显式登记消费
        tok = IngressToken(_ISSUE_PIN, "test_harness", entry="test_harness")
        _ISSUED["test_harness"] = tok
    return tok


def delegate_ingress(token: IngressToken, *, entry: str) -> IngressToken:
    """把真实 human ingress 降权为一次性程序续跑凭据。

    委派 token 保留原 human channel 以复用既有白名单，但显式标记 delegated，
    且只驻留进程内、不写 schedule.json；进程重启后自动唤醒安全降级为通知。
    """
    if not isinstance(token, IngressToken) or token.delegated or not is_whitelisted(token):
        raise ValueError("ingress 不可委派：必须是未委派的真实 human ingress")
    ref = str(entry or "").strip()
    if not ref:
        raise ValueError("delegated ingress entry 不能为空")
    return IngressToken(_ISSUE_PIN, token.channel, entry=f"scheduled:{ref}", delegated=True)


def is_whitelisted(token: object) -> bool:
    """凭据是否属白名单通道（frozenset O(1) 身份查找；委托单一真相源）。"""
    from llm_loop.core.trace_leak.channel_whitelist import whitelist_allows

    return whitelist_allows(token)
