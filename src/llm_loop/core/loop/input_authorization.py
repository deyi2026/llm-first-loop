"""Legacy latent-channel compatibility controls.

P1-A/P1-B removed runtime parsing of task continuation/reopen/cancel semantics. Current
user meaning and tool choice belong to the model under RULE-AI-23; this module retains
only the unrelated latent-channel compatibility switch.

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


def current_latent_channel_mode() -> str:
    """读取潜语义通道处置模式（每次现读，供灰度与测试 monkeypatch）."""
    mode = (
        str(os.environ.get(LATENT_CHANNEL_ENV, "") or DEFAULT_LATENT_CHANNEL_MODE).strip().lower()
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
