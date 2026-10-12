"""五阶段核心循环（M53 拆分包）: engine 主类 + 职责 mixin.

对外接口不变: `from llm_loop.core.loop import LoopEngine, LoopResult, ...` 继续可用。
（PEP 562 惰性门面: prompt_build/stages 反向引用 core.loop.* 时不再 eager 拉起
engine→build→stages 成环; 门面符号首次取用时解析并缓存。）
- engine.py: LoopEngine 主类（run 主流程 + 上下文构建 + 归档/记忆）
- signals.py: _SignalsMixin（信号检查）
- runtime.py: _RuntimeParamsMixin（运行时参数）
- engine_services/fallback.py: FallbackService（模型降级链）
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 静态类型解析走真实模块，运行时零导入
    from llm_loop.core.loop.engine import LoopEngine, LoopResult, format_tokens
    from llm_loop.core.session_snapshot import build_session_snapshot_text

__all__ = ["LoopEngine", "LoopResult", "build_session_snapshot_text", "format_tokens"]

_LAZY_EXPORTS = {
    "LoopEngine": ("llm_loop.core.loop.engine", "LoopEngine"),
    "LoopResult": ("llm_loop.core.loop.engine", "LoopResult"),
    "format_tokens": ("llm_loop.core.loop.engine", "format_tokens"),
    "build_session_snapshot_text": (
        "llm_loop.core.session_snapshot",
        "build_session_snapshot_text",
    ),
}


def __getattr__(name: str):  # noqa: ANN001, D103 - PEP 562 门面
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    import importlib

    value = getattr(importlib.import_module(module_name), attr)
    globals()[name] = value  # 首次解析后缓存，后续访问零开销
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
