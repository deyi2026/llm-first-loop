"""闸2 准入 + 闸3 策略（DESIGN §5.4；全部 fail-closed，纯函数无副作用）。

分工（刻意不合并，便于"哪道闸生效"可分辨）：
- 闸2：kind 是否被租约允许、租约是否有效/未过期/未用尽、并发配额、是否需有人在场。
- 闸3：路径是否落在 allowed_paths、params 形状、敏感目录拒绝。
- 闸4（沙盒）不在这里：它由现有 write_scope/bwrap 在真正落地时判定，
  返回 ``sandbox_denied``。闸3 与闸4 必须能各自独立拒绝（设计检查单 T7）。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from .errors import PeerError
from .kinds import KindSpec, get_kind
from .models import GrantRecord, iso, now_local, parse_ts

DEFAULT_MAX_READ_BYTES = 1_048_576
MAX_LIST_DEPTH = 3
MAX_TIMEOUT_S = 120

# 闸3 的敏感目录拒绝（读也不许）：与 allowed_paths 是"与"关系，不是替代。
_SENSITIVE_SUFFIXES: tuple[str, ...] = (
    os.path.join("data", "peer", "secrets"),
    os.path.join(".ssh"),
    os.path.join(".aws"),
    os.path.join(".gnupg"),
)


def _kind_spec(kind: str) -> KindSpec:
    spec = get_kind(kind)
    if spec is None:
        raise PeerError("policy_task_kind_not_allowed", kind)
    return spec


def require_kind_allowed(kind: str, grant: GrantRecord) -> KindSpec:
    spec = _kind_spec(kind)
    if kind not in tuple(grant.allowed_kinds):
        raise PeerError("policy_task_kind_not_allowed", f"{kind} not in grant {grant.grant_id}")
    return spec


def require_grant_active(
    grant: GrantRecord,
    *,
    running_tasks: int = 0,
    now: Any = None,
) -> GrantRecord:
    """闸2：撤销 > 上限缺失 > 过期 > 用尽 > 并发配额（顺序固定，回执可解释）。"""
    if grant.state == "revoked" or grant.revoked_at:
        raise PeerError("grant_revoked", grant.grant_id)
    if not grant.expires_at or int(grant.max_tasks_total) <= 0:
        raise PeerError("grant_unbounded", grant.grant_id)
    moment = now or now_local()
    try:
        expires = parse_ts(grant.expires_at)
    except ValueError:
        raise PeerError("grant_unbounded", f"bad expires_at: {grant.expires_at!r}") from None
    if moment >= expires:
        raise PeerError("grant_expired", f"{grant.grant_id} expired at {iso(expires)}")
    if int(grant.tasks_used) >= int(grant.max_tasks_total):
        raise PeerError("grant_exhausted", grant.grant_id)
    if running_tasks >= int(grant.max_concurrency):
        raise PeerError("quota_concurrency_exceeded", f"{running_tasks}/{grant.max_concurrency}")
    return grant


def require_supervision(spec: KindSpec, *, supervised: bool) -> None:
    if spec.supervised_only and not supervised:
        raise PeerError("requires_supervised_execution", spec.kind)


def _normalize_root(root: str) -> str:
    return os.path.realpath(os.path.expanduser(root))


def path_within(path: str, roots: Iterable[str]) -> bool:
    """realpath 包含判定（跟随符号链接后再比，避免 ../ 与 symlink 逃逸）。"""
    if not isinstance(path, str) or not path or not os.path.isabs(path):
        return False
    real = os.path.realpath(path)
    for root in roots:
        candidate = _normalize_root(root)
        if real == candidate:
            return True
        try:
            if os.path.commonpath([real, candidate]) == candidate:
                return True
        except ValueError:  # 不同盘符/相对混入
            continue
    return False


def is_sensitive_path(path: str) -> bool:
    real = os.path.realpath(path)
    return any(real.endswith(suffix) or f"{suffix}{os.sep}" in real for suffix in _SENSITIVE_SUFFIXES)


def require_path_allowed(path: str, allowed_paths: Iterable[str]) -> str:
    """闸3：返回 realpath，供执行器直接使用（避免 TOCTOU 二次解析差异）。"""
    if not isinstance(path, str) or not path or not os.path.isabs(path):
        raise PeerError("path_outside_allowed_paths", f"not an absolute path: {path!r}")
    if is_sensitive_path(path):
        raise PeerError("path_outside_allowed_paths", f"sensitive path: {path!r}")
    if not path_within(path, allowed_paths):
        raise PeerError("path_outside_allowed_paths", path)
    return os.path.realpath(path)


def _int_param(params: dict[str, Any], name: str, *, default: int, low: int, high: int) -> int:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PeerError("params_schema_invalid", f"{name} must be int in [{low},{high}]")
    return value


def validate_params(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """按 kind 收紧 params；未实现的 kind 只做"是对象"这一步（执行器再拒）。"""
    if not isinstance(params, dict):
        raise PeerError("params_schema_invalid", "params must be an object")
    spec = get_kind(kind)
    if spec is None:
        raise PeerError("policy_task_kind_not_allowed", kind)

    if kind in ("fs.read", "fs.list"):
        allowed = {"path", "max_bytes"} if kind == "fs.read" else {"path", "depth"}
        extra = sorted(set(params) - allowed)
        if extra:
            raise PeerError("params_schema_invalid", f"unexpected params: {extra}")
        if not isinstance(params.get("path"), str):
            raise PeerError("params_schema_invalid", "path is required")
        if kind == "fs.read":
            _int_param(params, "max_bytes", default=DEFAULT_MAX_READ_BYTES, low=1, high=DEFAULT_MAX_READ_BYTES)
        else:
            _int_param(params, "depth", default=1, low=1, high=MAX_LIST_DEPTH)
    elif kind == "fs.write":
        # 写侧 params 只允许"路径 + 恰好一个内容源 + 两个显式开关"。
        # 内容源二选一而不是二缺一顺延：缺省值会变成隐式语义，写错就是写错。
        allowed = {"path", "content_b64", "artifact_ref", "overwrite", "create_parents"}
        extra = sorted(set(params) - allowed)
        if extra:
            raise PeerError("params_schema_invalid", f"unexpected params: {extra}")
        if not isinstance(params.get("path"), str):
            raise PeerError("params_schema_invalid", "path is required")
        sources = [name for name in ("content_b64", "artifact_ref") if name in params]
        if len(sources) != 1:
            raise PeerError(
                "params_schema_invalid",
                "exactly one of content_b64/artifact_ref is required",
            )
        if "content_b64" in params and not isinstance(params["content_b64"], str):
            raise PeerError("params_schema_invalid", "content_b64 must be a string")
        if "artifact_ref" in params:
            ref = params["artifact_ref"]
            if not isinstance(ref, str) or not ref.startswith("artifact://v1/"):
                raise PeerError(
                    "params_schema_invalid", "artifact_ref must be artifact://v1/<sha256>"
                )
        for flag in ("overwrite", "create_parents"):
            if flag in params and not isinstance(params[flag], bool):
                raise PeerError("params_schema_invalid", f"{flag} must be bool")
    elif kind == "shell.exec":
        if not isinstance(params.get("argv"), list) or not params["argv"]:
            raise PeerError("params_schema_invalid", "argv must be a non-empty array")
        if any(not isinstance(a, str) for a in params["argv"]):
            raise PeerError("params_schema_invalid", "argv items must be strings")
        _int_param(params, "timeout_s", default=MAX_TIMEOUT_S, low=1, high=MAX_TIMEOUT_S)
        if "cwd" in params and not isinstance(params["cwd"], str):
            raise PeerError("params_schema_invalid", "cwd must be a string")
    elif kind == "desktop.screenshot":
        if "display" in params and not isinstance(params["display"], str):
            raise PeerError("params_schema_invalid", "display must be a string")
    elif kind == "desktop.click":
        for axis in ("x", "y"):
            if isinstance(params.get(axis), bool) or not isinstance(params.get(axis), int):
                raise PeerError("params_schema_invalid", f"{axis} must be int")
        if not isinstance(params.get("frame_ref"), str):
            raise PeerError("params_schema_invalid", "frame_ref is required")
    elif kind == "desktop.focus_probe":
        if params:
            raise PeerError("params_schema_invalid", "desktop.focus_probe takes no params")
    return params


def params_paths(kind: str, params: dict[str, Any]) -> tuple[str, ...]:
    """闸3 需要校验的路径集合（按 kind 取）。"""
    if kind in ("fs.read", "fs.list", "fs.write"):
        path = params.get("path")
        return (path,) if isinstance(path, str) else ()
    if kind == "shell.exec":
        cwd = params.get("cwd")
        return (cwd,) if isinstance(cwd, str) else ()
    return ()


def evaluate(
    *,
    kind: str,
    params: dict[str, Any],
    grant: GrantRecord,
    supervised: bool = False,
    running_tasks: int = 0,
    now: Any = None,
) -> KindSpec:
    """闸2+闸3 合成判定；通过返回 KindSpec，否则抛 PeerError（调用方落 denied 记录）。"""
    spec = require_kind_allowed(kind, grant)
    require_grant_active(grant, running_tasks=running_tasks, now=now)
    require_supervision(spec, supervised=supervised)
    validate_params(kind, params)
    for path in params_paths(kind, params):
        require_path_allowed(path, grant.allowed_paths)
    return spec
