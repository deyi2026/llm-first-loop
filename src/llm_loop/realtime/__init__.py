"""LFL 实时多模态（realtime_multimodal）子包。

首版聚焦本地实时语音栈接线（见 `docs/DESIGN-20261023-realtime-multimodal-architecture.md` v1.3）。

本子包只承载模型不可替代的事实边界：连接归属、身份、字节格式、精确代次、
已提交状态、资源上限与去重；语义理解、任务取舍与答案组织仍由模型承担。
"""

from __future__ import annotations

__all__: list[str] = []
