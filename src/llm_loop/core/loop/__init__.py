"""五阶段核心循环（M53 拆分包）: engine 主类 + 职责 mixin.

对外接口不变: `from llm_loop.core.loop import LoopEngine, LoopResult, ...` 继续可用。
- engine.py: LoopEngine 主类（run 主流程 + 上下文构建 + 归档/记忆）
- signals.py: _SignalsMixin（信号检查）
- runtime.py: _RuntimeParamsMixin（运行时参数）
- engine_services/fallback.py: FallbackService（模型降级链）
"""

from llm_loop.core.loop.engine import (
    LoopEngine,
    LoopResult,
    format_tokens,
)
from llm_loop.core.session_snapshot import build_session_snapshot_text

__all__ = ["LoopEngine", "LoopResult", "build_session_snapshot_text", "format_tokens"]
