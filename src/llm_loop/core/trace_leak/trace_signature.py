"""trace_signature 内容特征兜底检测（tasks 4.4，design D2，spec 5.4.1-2）.

预编译正则单遍扫描，以 #280/#290 实证结构为模板脱敏构造（tests/fixtures/
trace_leak/）：思考过程标记 + 工具调用命令组合模式。

配置 ``LFL_TRACE_SIGNATURE``：``off``（默认）/ ``warn``（仅告警）。
warn 模式只记 ``leak.signature_warned`` 事件不改视图、默认不拦截
（spec 5.4.1-2，避免误伤用户粘贴代码/日志）；人类通道凭据消息
（metadata 带 ingress_channel）永不进入拦截分支（spec 5.4.3-2）；
正则异常 fail-open 不命中返回。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

SIGNATURE_ENV = "LFL_TRACE_SIGNATURE"
DEFAULT_SIGNATURE_MODE = "off"

# #280/#290 结构模板（实证提取，脱敏通用化）：
# - 行首「思考过程」独立标记（多次出现）
# - 「自动」动作标记 + 工具命令（python3 -c / grep / sed / git / npm）
_TRACE_THINK_MARK = re.compile(r"(?m)^\s*思考过程\s*$")
_TOOL_CMD_MARK = re.compile(
    r"(?m)^(python3? -[cs]\b|grep\b|sed\b|npm \w+|git \w+|rg\b|awk\b)"
)


@dataclass(frozen=True)
class SignatureVerdict:
    """特征扫描回执。"""

    hit: bool
    basis: str
    mode: str


def current_signature_mode() -> str:
    mode = str(os.environ.get(SIGNATURE_ENV, "") or DEFAULT_SIGNATURE_MODE).strip().lower()
    return mode if mode in ("off", "warn") else DEFAULT_SIGNATURE_MODE


def content_matches_signature(content: str) -> bool:
    """思考过程标记与工具调用命令组合同时命中即轨迹特征（fail-open）。"""
    try:
        text = str(content or "")
        return bool(_TRACE_THINK_MARK.search(text)) and bool(_TOOL_CMD_MARK.search(text))
    except Exception:  # noqa: BLE001 — 正则异常不命中返回（fail-open）
        return False


def trace_signature_scan(content: str, *, has_human_credential: bool = False) -> SignatureVerdict:
    """二级防御扫描入口（默认 off；warn 仅告警不拦截）.

    has_human_credential: 消息是否带人类通道凭据快照——True 时永不进入
    拦截分支（spec 5.4.3-2）。
    """
    mode = current_signature_mode()
    if mode != "warn" or has_human_credential:
        return SignatureVerdict(False, f"mode={mode} 不扫描或人类凭据消息豁免", mode)
    hit = content_matches_signature(content)
    return SignatureVerdict(
        hit,
        "思考过程标记 + 工具调用命令组合命中" if hit else "特征未命中",
        mode,
    )
