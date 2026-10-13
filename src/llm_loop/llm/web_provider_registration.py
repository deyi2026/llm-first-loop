"""外部 web provider 注册接缝（web-carveout §2.2，D2/D3 决策）。

中间件不再内置 deepseek/chatgpt 页面自动化 client（已剥离至独立项目
lfl-web-providers）；本模块按配置动态加载外部注册模块并取回：

- ``web_provider_specs() -> dict[str, ProviderSpec]``：模型目录条目
- ``web_client_factories(settings, *, transport_observer) -> dict[str, callable]``：
  外部 client 构造器（model_ref -> builder）

失败语义分级（§2.2）：
- 未配置 ``web_providers_module`` → 静默返回空（合法形态，与旧 enabled=0 等价）
- 配置了但 import/属性缺失/调用抛错/返回类型不符 → warning（含原因）+ 返回空，
  对齐 providers.py 既有 degraded 风格——不静默吞掉「用户明确想要 web client」
  的失败，也不把可选通道故障升级为引擎构建失败。

``web_providers_module_path``（可选）在加载前注入 sys.path，使独立项目无需
安装进中间件环境（避免 pip 级循环依赖：独立项目测试侧依赖本包）。
"""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _load_registration_module(settings: Any) -> Any | None:
    name = str(getattr(settings, "web_providers_module", "") or "").strip()
    if not name:
        return None
    path = str(getattr(settings, "web_providers_module_path", "") or "").strip()
    if path and path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(name)


def load_web_provider_specs(settings: Any) -> dict[str, Any]:
    """取外部模块的 ProviderSpec 目录条目（失败降级见模块 docstring）。"""
    try:
        module = _load_registration_module(settings)
        if module is None:
            return {}
        specs = module.web_provider_specs()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - 可选通道 fail-soft，不冒泡
        logger.warning(
            "web provider 注册模块加载失败（web_provider_specs），web 通道不注册：%s: %s",
            type(exc).__name__,
            exc,
        )
        return {}
    from llm_loop.llm.providers import ProviderSpec

    if not isinstance(specs, dict) or not all(
        isinstance(spec, ProviderSpec) for spec in specs.values()
    ):
        logger.warning(
            "web provider 注册模块 web_provider_specs() 返回类型异常"
            "（期望 dict[str, ProviderSpec]）；web 通道不注册"
        )
        return {}
    return dict(specs)


def load_web_client_factories(
    settings: Any, *, transport_observer: Any
) -> dict[str, Callable[[], Any]]:
    """取外部模块的 client 构造器（失败降级见模块 docstring）。"""
    try:
        module = _load_registration_module(settings)
        if module is None:
            return {}
        factories = module.web_client_factories(  # type: ignore[attr-defined]
            settings, transport_observer=transport_observer
        )
    except Exception as exc:  # noqa: BLE001 - 可选通道 fail-soft，不冒泡
        logger.warning(
            "web provider 注册模块加载失败（web_client_factories），web 通道不注册：%s: %s",
            type(exc).__name__,
            exc,
        )
        return {}
    if not isinstance(factories, dict) or not all(
        callable(builder) for builder in factories.values()
    ):
        logger.warning(
            "web provider 注册模块 web_client_factories() 返回类型异常"
            "（期望 dict[str, callable]）；web 通道不注册"
        )
        return {}
    return dict(factories)
