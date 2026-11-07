"""kind 注册表（受控端能力的唯一权威）。

与 manifest.kinds 同构：能力声明是路由依据，不是权限；权限在 PeerGrant。
不变量（scripts/verify_peer_schemas.py 的 invariant 检查）：
``idempotency_class == "non_idempotent"`` ⇒ ``supervised_only must be True``。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KindSpec:
    kind: str
    idempotency_class: str
    supervised_only: bool
    params_schema_hint: str
    default_enabled: bool = True


DEFAULT_KINDS: tuple[KindSpec, ...] = (
    KindSpec("fs.read", "idempotent", False, "path: 授权内绝对路径; max_bytes<=1048576"),
    KindSpec("fs.list", "idempotent", False, "path: 授权内绝对路径; depth<=3"),
    KindSpec(
        "fs.write",
        "non_idempotent",
        True,
        "path: 授权内绝对路径; content_b64 或 artifact_ref; 需有人在场",
    ),
    KindSpec(
        "shell.exec",
        "non_idempotent",
        True,
        "argv: 数组(不经 shell); cwd 在授权内; timeout_s<=120; 默认不启用",
        default_enabled=False,
    ),
    KindSpec("desktop.screenshot", "idempotent", False, "display: 可选; 仅 X11"),
    KindSpec(
        "desktop.click",
        "non_idempotent",
        True,
        "x,y: 必须来自本端采集帧; frame_ref; 需有人在场",
    ),
    KindSpec("desktop.focus_probe", "idempotent", False, "none"),
)

KINDS: dict[str, KindSpec] = {spec.kind: spec for spec in DEFAULT_KINDS}


def get_kind(kind: str) -> KindSpec | None:
    return KINDS.get(kind)


def known_kinds() -> tuple[str, ...]:
    return tuple(KINDS)


def manifest_kinds(enabled: set[str] | None = None) -> list[dict[str, object]]:
    """manifest.kinds 载荷：默认只暴露 default_enabled 的 kind。"""
    allowed = enabled if enabled is not None else {k for k, s in KINDS.items() if s.default_enabled}
    return [
        {
            "kind": spec.kind,
            "idempotency_class": spec.idempotency_class,
            "supervised_only": spec.supervised_only,
            "params_schema_hint": spec.params_schema_hint,
        }
        for spec in DEFAULT_KINDS
        if spec.kind in allowed
    ]
