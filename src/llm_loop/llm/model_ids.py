"""模型 ID 归一（catalog 层, 2026-09-12 双命名收口）.

本地推理服务（LM Studio 等）对**同一物理模型**可能同时暴露两种 ID 形态:
- HF 风格 org/name:      "ornith-ai/Ornith-1.5-35B-A3B-MLX"
- 文件系统绝对路径:       "~/.lmstudio/models/ornith-ai/Ornith-1.5-35B-A3B-MLX"

此前 catalog 层把两者当不同模型列出, switch_model 用错形态即解析失败。

归一只做**确定性、可逆**的形态变换, 不做模糊猜测匹配:
- LM Studio 路径形态: 截取 ".lmstudio/models/" 之后的尾部作为规范形态
- HF cache 形态:       "models--org--name" → "org/name"
- 其余形态原样返回（视为已规范）

边界与不保证:
- 只用于**解析与展示**（catalog 层）; 注册表与 wire 调用仍使用注册时的原始 ID,
  对远端服务零行为差异。
- 不同物理模型恰好共享规范形态时（理论可能）, resolve 侧的别名回退会因
  多候选而拒绝, 不会静默选错（fail-loud）。
"""

from __future__ import annotations

import re

_LMSTUDIO_MARKER = ".lmstudio/models/"
_HF_CACHE_RE = re.compile(r"^models--(?P<org>[^/]+)--(?P<name>[^/]+)$")


def canonical_model_id(model_id: str) -> str:
    """返回模型 ID 的规范形态; 无法归一的输入原样返回."""
    if not model_id:
        return model_id
    idx = model_id.find(_LMSTUDIO_MARKER)
    if idx >= 0:
        return model_id[idx + len(_LMSTUDIO_MARKER):].strip("/")
    match = _HF_CACHE_RE.match(model_id)
    if match:
        return f"{match.group('org')}/{match.group('name')}"
    return model_id


def is_alias_form(model_id: str) -> bool:
    """True = 该 ID 是别名形态（非其自身规范形态）."""
    return canonical_model_id(model_id) != model_id
