"""Profile class 三级授权判定（DESIGN-20261005-browser-channel-hardening v4 §4.2，S2）。

纯逻辑、无 I/O：输入四个 env 归一化后的原始串，输出不可变决定。
默认档（class 空或 dedicated）永远 allowed——与 S2 之前行为完全一致；
real 档要求显式人工 ACK，缺/格式坏/过期 ⇒ allowed=False ⇒ factory 拒绝注册全部
browser 工具（fail-closed）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

__all__ = [
    "AckRecord",
    "ProfileClassDecision",
    "evaluate_profile_class",
    "ack_digest",
    "annotation_for",
]

_LEGAL_CLASSES = ("", "dedicated", "real")
_LEGAL_MODES = ("shadow", "enforce")
_DATE_FORMAT = "%Y-%m-%d"


@dataclass(frozen=True)
class AckRecord:
    subject: str
    scope: str
    expires: date

    def canonical(self) -> str:
        return f"{self.subject}|{self.scope}|{self.expires.strftime(_DATE_FORMAT)}"


@dataclass(frozen=True)
class ProfileClassDecision:
    profile_class: str  # "dedicated" | "real"（已归一；非法值在拒绝决定里原样保留于 reason）
    allowed: bool
    reason: str
    ack: AckRecord | None = None
    attestation_mode: str = "enforce"  # shadow|enforce；S3b 消费，S2 只做合法性门


def _parse_expires(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), _DATE_FORMAT).date()
    except ValueError:
        return None


def evaluate_profile_class(
    class_raw: str,
    ack_raw: str,
    paths_raw: str,
    mode_raw: str = "enforce",
    *,
    today: date | None = None,
) -> ProfileClassDecision:
    """根据三/四键原始值出决定。today 可注入供测试与过期边界判定。"""
    today = today or date.today()
    klass = (class_raw or "").strip().lower()
    mode = (mode_raw or "enforce").strip().lower()
    ack_raw = (ack_raw or "").strip()
    paths_raw = (paths_raw or "").strip()

    if klass not in _LEGAL_CLASSES:
        return ProfileClassDecision(
            profile_class=klass or "dedicated",
            allowed=False,
            reason=(
                f"LFL_BROWSER_PROFILE_CLASS 非法值 {klass!r}：合法值为 dedicated/real"
                "（留空=dedicated 默认档）——fail-closed 拒绝注册 browser 工具"
            ),
            attestation_mode=mode if mode in _LEGAL_MODES else "enforce",
        )

    if mode not in _LEGAL_MODES:
        return ProfileClassDecision(
            profile_class="real" if klass == "real" else "dedicated",
            allowed=False,
            reason=(
                f"LFL_BROWSER_ATTESTATION_MODE 非法值 {mode_raw!r}：合法值为 shadow/enforce"
                "——fail-closed 拒绝注册 browser 工具"
            ),
        )

    if klass != "real":
        # 默认档：PATHS/ACK 不参与判定（配置了也只作为冗余存储，不产生行为差异）
        return ProfileClassDecision(
            profile_class="dedicated",
            allowed=True,
            reason="default tier: profile_class 空/dedicated，行为与 S2 之前一致",
            attestation_mode=mode,
        )

    # ── real 档 ──
    if not ack_raw:
        return ProfileClassDecision(
            profile_class="real",
            allowed=False,
            reason=(
                "profile_class=real 需要显式人工授权 LFL_BROWSER_REAL_PROFILE_ACK"
                "（格式 <subject>|<scope>|<expires YYYY-MM-DD>），当前为空"
                "——fail-closed 拒绝注册 browser 工具"
            ),
            attestation_mode=mode,
        )

    parts = ack_raw.split("|")
    if len(parts) != 3:
        return ProfileClassDecision(
            profile_class="real",
            allowed=False,
            reason=(
                f"LFL_BROWSER_REAL_PROFILE_ACK 格式非法（须恰 3 段 <subject>|<scope>|"
                f"<expires YYYY-MM-DD>，实得 {len(parts)} 段）——fail-closed 拒绝注册"
            ),
            attestation_mode=mode,
        )
    subject, scope, expires_raw = (p.strip() for p in parts)
    if not subject or not scope:
        return ProfileClassDecision(
            profile_class="real",
            allowed=False,
            reason="LFL_BROWSER_REAL_PROFILE_ACK 的 subject/scope 不能为空——fail-closed 拒绝注册",
            attestation_mode=mode,
        )
    expires = _parse_expires(expires_raw)
    if expires is None:
        return ProfileClassDecision(
            profile_class="real",
            allowed=False,
            reason=(
                f"LFL_BROWSER_REAL_PROFILE_ACK 过期日格式非法 {expires_raw!r}"
                f"（须 YYYY-MM-DD）——fail-closed 拒绝注册"
            ),
            attestation_mode=mode,
        )
    if expires < today:
        return ProfileClassDecision(
            profile_class="real",
            allowed=False,
            reason=(
                f"LFL_BROWSER_REAL_PROFILE_ACK 已于 {expires} 过期（today={today}）"
                "——fail-closed 拒绝注册 browser 工具"
            ),
            attestation_mode=mode,
        )

    # PATHS 白名单格式预检（空=非白名单内指回即拒绝；"none"=禁用白名单；其余须绝对路径）
    if paths_raw and paths_raw != "none":
        bad = [p for p in (s.strip() for s in paths_raw.split(",")) if p and not p.startswith("/")]
        if bad:
            return ProfileClassDecision(
                profile_class="real",
                allowed=False,
                reason=(
                    f"LFL_BROWSER_REAL_PROFILE_PATHS 含相对路径 {bad}（须绝对路径、"
                    '逗号分隔，或 "none"）——fail-closed 拒绝注册'
                ),
                ack=None,
                attestation_mode=mode,
            )

    return ProfileClassDecision(
        profile_class="real",
        allowed=True,
        reason=f"real tier: ACK subject={subject!r} scope={scope!r} expires={expires}",
        ack=AckRecord(subject=subject, scope=scope, expires=expires),
        attestation_mode=mode,
    )


def ack_digest(ack: AckRecord) -> str:
    return hashlib.sha256(ack.canonical().encode("utf-8")).hexdigest()[:16]


def annotation_for(decision: ProfileClassDecision) -> dict[str, Any] | None:
    """real 且合法时返回回执审计注记；默认档返回 None（输出字节级不变）。"""
    if decision.profile_class != "real" or not decision.allowed or decision.ack is None:
        return None
    return {
        "profile_class": "real",
        "ack_digest": ack_digest(decision.ack),
        "ack_expires": decision.ack.expires.strftime(_DATE_FORMAT),
    }
