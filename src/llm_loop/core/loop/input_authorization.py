"""R8.24-E E-D5 / E-D1 路线 1（E-3.x）: input-side 授权 resolver.

核心原则（设计包 E §3）：
- ``task_active`` 从 ACTIVE_STATE 收紧为 USER_AUTHORIZED_STATE——"恰有
  in_progress"不再自动注入；仅当本轮用户输入命中"继续/恢复上次任务"类
  明确指令时，由 input-side resolver 授权一次。
- memory 显式指代（"按我之前的 X""你记得 Y 吗"）→ 授权一次 input-side
  retrieval（检索结果以真实数据投影，非自动 grant）。
- 识别词表外置可配置（漏召回兜底 = 模型可问用户——语义决策权在模型侧，
  不追求召回率 100%）。
- shadow 期两检测器只记录 ``would_authorize``（不改变注入行为）；
  enforce 期授权绑定事件落决策日志（E-G2/E-G5 双断言的判据源）。

开关（E-1.x，批 E1①/②）：
- ``LFL_LATENT_CHANNEL`` 三态 on/shadow/off。**本批收尾落地默认 off（enforce，
  三通道退出）**。shadow 语义 = 通道零注入 + ``would_inject`` 计数事件留痕
  （观测不注入——SLOTS 注册表已按 E-G6 退役，"照旧投影"不可恢复；见批内
  申报）。on = 回滚通道意图（行为等同 shadow + 警告日志；producer 注册表
  退役后无注入对象）。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

LATENT_CHANNEL_ENV = "LFL_LATENT_CHANNEL"
DEFAULT_LATENT_CHANNEL_MODE = "off"
_VALID_LATENT_CHANNEL_MODES = frozenset({"on", "shadow", "off"})

# ── task_active 授权触发词表（从严：仅明确"继续/恢复"类指令）──
# 从严理由（任务书 E-3.1①）：单独"继续"过泛（日常对话高频词）；要求明确
# 指向"上次任务/刚才任务"或任务动作语境。B-D6 E18 硬边界结束/暂停后的
# 用户"继续"指令经完整短语形态（"继续刚才的任务"等）命中。
TASK_CONTINUATION_KEYWORDS: tuple[str, ...] = (
    "继续上次任务",
    "恢复上次任务",
    "接着上次任务",
    "继续上次的任务",
    "恢复上次的任务",
    "接着上次的任务",
    "继续刚才的任务",
    "恢复刚才的任务",
    "继续刚才的任务",
    "接着刚才的任务",
    "恢复刚才",
    "继续任务",
    "恢复任务",
    "继续这个任务",
    "恢复这个任务",
    "接着这个任务",
    "继续上次工作",
    "恢复上次工作",
    "继续上次没做完",
    "接着上次没做完",
)

# ── memory 显式指代检测词表（E-D1 路线 1）──
MEMORY_REFERENCE_KEYWORDS: tuple[str, ...] = (
    "按我之前",
    "你记得",
    "我记得之前",
    "我之前说过",
    "我之前提过",
    "之前告诉过你",
    "上次我们讨论",
    "上次提到",
    "之前聊过",
    "你之前记录",
    "我上次说",
    "之前我说",
)


def current_latent_channel_mode() -> str:
    """读取潜语义通道处置模式（每次现读，供灰度与测试 monkeypatch）."""
    mode = (
        str(os.environ.get(LATENT_CHANNEL_ENV, "") or DEFAULT_LATENT_CHANNEL_MODE)
        .strip()
        .lower()
    )
    if mode not in _VALID_LATENT_CHANNEL_MODES:
        return DEFAULT_LATENT_CHANNEL_MODE
    if mode == "on":
        logger.warning(
            "LFL_LATENT_CHANNEL=on：producer 注册表已按 E-G6 退役（E-5.1），"
            "on 回滚意图无注入对象，行为等同 shadow（计数观测）；"
            "完整回滚请 git revert 本批提交"
        )
    return mode


def _configured_keywords(base: tuple[str, ...], env: str) -> tuple[str, ...]:
    """词表外置可配置：env 逗号分隔覆盖；未设置用内置从严词表."""
    raw = str(os.environ.get(env, "") or "").strip()
    if not raw:
        return base
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or base


def detect_task_continuation(text: str) -> bool:
    """task_active 授权检测（从严触发词表 + /continue 续聊指令；词表可经 env 配置).

    ``/continue`` 与飞书 ``_try_handle_continue_command`` 同口径（strip+lower 精确匹配），
    是明确的续聊授权信号；不影响 memory 显式指代检测。
    """
    t = str(text or "")
    if not t:
        return False
    if t.strip().lower() == "/continue":
        return True
    keywords = _configured_keywords(
        TASK_CONTINUATION_KEYWORDS, "LFL_TASK_CONTINUE_KEYWORDS"
    )
    return any(k in t for k in keywords)


def detect_memory_reference(text: str) -> bool:
    """memory 显式指代检测（E-D1 路线 1；授权一次 input-side retrieval）."""
    t = str(text or "")
    if not t:
        return False
    keywords = _configured_keywords(
        MEMORY_REFERENCE_KEYWORDS, "LFL_MEMORY_REF_KEYWORDS"
    )
    return any(k in t for k in keywords)
