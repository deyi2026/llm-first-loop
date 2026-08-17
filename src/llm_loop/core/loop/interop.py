"""协调通道 inbox 注入 mixin（RULE-AI-14 实现层，2026-08-16）.

程序级自动感知: DSH→LFL 待处理消息每轮 run 装配时注入 LLM 上下文——
不再依赖提示词引导（LLM 可能跳过）。协议见 data/interop/INTEROP.md。

设计要点:
- 只读文件系统，不触发 run、不占会话锁（接收方在自己 run 里顺手读）
- 临时 system 消息，不写会话历史: 处理后文件移走即幂等，未处理每轮重新注入
- 不打 injected_system 标记: 该标记在本地 provider 下会被 skip 跳过提交——
  协调待办是核心消息，所有 provider 均须可见
- 注入位置在 memory 之后、历史之前（P1-10 前缀稳定）: system_prompt+memory
  段在有/无消息轮字节级一致，服务端前缀缓存命中不因 inbox 存在与否而失配；
  仅 history 段起点随消息轮偏移（低频、量小、单轮，锚点换算已计入）
- fail-open: 目录缺失/读失败/格式坏 → 跳过，异常返回空（不阻塞主流程）
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条)


from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from llm_loop.core.message import Message, MessageSource

logger = logging.getLogger(__name__)

_INTEROP_INBOX_REL = Path("interop") / "lfl_to_dsh" / "pending"


class _InteropMixin:
    """协调通道（RULE-AI-14）程序级注入."""

    def _interop_inbox_messages(self) -> list[Message]:
        """扫描协调通道 inbox 待处理消息（DSH→LFL）.

        基准路径: LFL_DATA_DIR/interop/lfl_to_dsh/pending（与 web/routes.py 一致）。
        返回临时 system 消息列表；无消息/异常 → 空列表。
        """
        try:
            base = Path(os.environ.get("LFL_DATA_DIR", "data")) / _INTEROP_INBOX_REL
            if not base.is_dir():
                return []
            out: list[Message] = []
            # 审查 P2 修复: 注入上限——pending 堆积（如 DSH 批量发消息）时
            # 只注入最新 8 条，防单轮上下文被协调消息撑爆（剩余下轮再注入）
            _MAX_INBOX_INJECT = 8
            files = sorted(base.glob("*.json"))
            for f in files[-_MAX_INBOX_INJECT:]:
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue  # 读失败/格式坏 → 跳过（fail-open）
                if d.get("status") != "pending":
                    continue
                body = str(d.get("body", "")).strip()
                if not body:
                    continue
                out.append(Message(
                    role="system",
                    content=(
                        f"[外部协调·from DSH] {d.get('id', f.stem)}"
                        f"[{d.get('topic', '')}] {body}\n"
                        f"（文件: data/interop/lfl_to_dsh/pending/{f.name}；"
                        f"处理完按协议 status 改 done 并移入 done/）"
                    ),
                    source=MessageSource.SYSTEM,
                ))
            if len(files) > _MAX_INBOX_INJECT:
                out.insert(0, Message(
                    role="system",
                    content=(
                        f"[外部协调] 另有 {len(files) - _MAX_INBOX_INJECT} 条待处理消息"
                        f"（超出单轮注入上限 {_MAX_INBOX_INJECT}，将在后续轮次注入）"
                    ),
                    source=MessageSource.SYSTEM,
                ))
            return out
        except Exception:
            logger.warning("协调通道 inbox 扫描失败（fail-open）", exc_info=True)
            return []

    def _inject_interop_messages(self, base: list[Message], prefix_len: int) -> tuple[list[Message], int]:
        """装配点调用: inbox 消息注入到 memory 之后、历史之前（返回注入后的 base 与 prefix_len）.

        engine._build_llm_messages 调用（每轮 run 必感知）；任何异常回落原值（fail-open）。
        注入位置语义（2026-08-16 优化，P1-10 前缀稳定）:
        - base[:prefix_len] = memory 段（前置注入，字节级稳定）
        - inbox 插入 memory 之后 → 与 memory 同机制: 最终由 build_history_messages 的
          _append_or_merge（P1-FEISHU）合并追加进 system_prompt 末尾——追加式合并保持
          system 原内容前缀命中（服务端 KV 前缀缓存），有消息轮仅重算 inbox 段
          （=其自身长度，几百字符一次性）；无消息轮零影响
        - prefix_len 仍 +len(inbox)（锚点换算口径不变: history 在完整序列中的起始偏移）
        """
        try:
            inbox = self._interop_inbox_messages()
            if inbox:
                return base[:prefix_len] + inbox + base[prefix_len:], prefix_len + len(inbox)
        except Exception:
            logger.warning("协调通道 inbox 注入失败（fail-open）", exc_info=True)
        return base, prefix_len
