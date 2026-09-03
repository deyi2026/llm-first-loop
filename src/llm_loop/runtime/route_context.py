"""RouteContext——实例路由三元组进程级一次解析（spec 5.3.1 / design D6·C-1）.

消除事故归因盲区①：审计行必须携带 instance/zone/route（纯观测、单一 SoT、
零新增 I/O——随 ActionTraceItem.to_dict() 顺带序列化，禁止独立落盘通道）。

解析规则（spec 6.4 取值域）：
- instance: LFL_INSTANCE 显式优先，缺省 f"{hostname}-{pid}"（进程内稳定）
- zone:     LFL_ZONE 显式优先，缺省由 compute_identity().workspace_root 路径
            含 "mirror" 段推导（复用 runtime/identity.py 事实，不耦合
            RUNTIME_IDENTITY_MODE）；取值域 {主区, 镜像, unknown}
- route:    LFL_ROUTE 显式优先，缺省 unknown；取值域
            {feishu, web, cli, scheduler, unknown}

显式值越界一律回退 unknown；首次解析含 unknown 字段时经注入的审计回调记
route.missing 恰一次（缺失字段列表入 detail，不逐条刷屏，spec 6.5.4）；
解析全程 fail-open（异常 → 三字段 unknown，spec 5.3.3-1）。
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_VALID_ZONES = {"主区", "镜像", "unknown"}
_VALID_ROUTES = {"feishu", "web", "cli", "scheduler", "unknown"}

_route_context: RouteContext | None = None
_route_missing_recorded = False
_route_audit_fn: Callable[[str, str, str], None] | None = None


@dataclass(frozen=True)
class RouteContext:
    """路由三元组（进程级冻结单例，spec 6.4）."""

    instance: str
    zone: str
    route: str


def set_route_audit_fn(fn: Callable[[str, str, str], None] | None) -> None:
    """注入 route.missing 留痕回调（fn(phase, action_type, detail)）.

    对齐 status_provider 回调注入风格；未注入时缺失事件静默（纯读取零副作用）。
    """
    global _route_audit_fn
    _route_audit_fn = fn


def reset_route_context() -> None:
    """清除进程级缓存（测试隔离钩子，生产路径不调用）."""
    global _route_context, _route_missing_recorded
    _route_context = None
    _route_missing_recorded = False


def _env_or_none(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _valid_or_unknown(value: str, valid: set[str]) -> str:
    return value if value in valid else "unknown"


def _derive_zone() -> str:
    # 复用 identity 既有事实（runtime/identity.py:95-125）：workspace_root 路径
    # 含 "mirror" 段 → 镜像，否则主区；identity 解析异常由调用方 fail-open 兜底
    from llm_loop.runtime.identity import compute_identity

    root = compute_identity().workspace_root
    return "镜像" if "mirror" in Path(root).parts else "主区"


def _resolve() -> RouteContext:
    instance = _env_or_none("LFL_INSTANCE") or f"{socket.gethostname()}-{os.getpid()}"
    explicit_zone = _env_or_none("LFL_ZONE")
    zone = (
        _valid_or_unknown(explicit_zone, _VALID_ZONES)
        if explicit_zone
        else _derive_zone()
    )
    route = _valid_or_unknown(_env_or_none("LFL_ROUTE"), _VALID_ROUTES)
    return RouteContext(instance=instance, zone=zone, route=route)


def _record_missing_once(ctx: RouteContext) -> None:
    global _route_missing_recorded
    missing = [k for k in ("instance", "zone", "route") if getattr(ctx, k) == "unknown"]
    if not missing or _route_missing_recorded:
        return
    _route_missing_recorded = True
    fn = _route_audit_fn
    if fn is None:
        return
    try:
        fn("runtime.route", "route.missing", f"missing={','.join(missing)}")
    except Exception:  # noqa: BLE001 — 留痕失败不影响主读取（fail-open）
        logger.debug("route.missing 留痕失败（fail-open）", exc_info=True)


def get_route_context() -> RouteContext:
    """进程级一次解析 + 缓存（首次访问懒加载）；纯读取无副作用（除首次留痕）."""
    global _route_context
    if _route_context is None:
        try:
            _route_context = _resolve()
        except Exception:  # noqa: BLE001 — 解析全程 fail-open（spec 5.3.3-1）
            logger.warning("路由三元组解析失败（fail-open 全 unknown）", exc_info=True)
            _route_context = RouteContext(instance="unknown", zone="unknown", route="unknown")
        _record_missing_once(_route_context)
    return _route_context
