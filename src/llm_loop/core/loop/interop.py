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
import time
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

        notify 自动归档（EVO-20260817-c35c9178，已人工 accepted）:
        - topic=notify 通知类消息首见仍注入回显（协议可见性不变，AI 按协议处理归档）
        - 同指纹 (from, ref, body) 已注入过的 notify → 不重复注入 + 自动归档
          （status→done + 移入 done/）——防高频通知堆积持续破坏前缀缓存
          （RULE-AI-16 注入最小化；实证: 14 条 job 通知堆积 → 每轮注入漂移 → 命中率 8.2%）
        - coordinate/task 类消息保持原协议（注入 + AI 处理），不自动归档
        """
        try:
            base = Path(os.environ.get("LFL_DATA_DIR", "data")) / _INTEROP_INBOX_REL
            if not base.is_dir():
                return []
            out: list[Message] = []
            # 审查 P2 修复: 注入上限——pending 堆积（如 DSH 批量发消息）时
            # 只注入最新 8 条，防单轮上下文被协调消息撑爆（剩余下轮再注入）
            _max_inbox_inject = 8  # 注入上限（函数内局部，小写命名）
            files = sorted(base.glob("*.json"))
            # EVO-20260817-c35c9178: notify 已注入指纹（进程级，重启后 pending 已 done 无重复）
            seen = getattr(self, "_notify_injected", None)
            if seen is None:
                seen = self._notify_injected = set()
            notify_archives: list[Path] = []  # 命中指纹 → 本轮自动归档
            for f in files[-_max_inbox_inject:]:
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue  # 读失败/格式坏 → 跳过（fail-open）
                if d.get("status") != "pending":
                    continue
                body = str(d.get("body", "")).strip()
                if not body:
                    continue
                if d.get("topic") == "notify":
                    fp = (str(d.get("from", "")), str(d.get("ref", "")), body)
                    if fp in seen:
                        notify_archives.append(f)  # 重复通知 → 归档不注入（幂等）
                        continue
                    seen.add(fp)                   # 首见 → 注入并记录指纹
                out.append(Message(
                    role="system",
                    content=(
                        f"[外部协调·from DSH] {d.get('id', f.stem)}"
                        f"[{d.get('topic', '')}] {body}\n"
                        f"（文件: data/interop/lfl_to_dsh/pending/{f.name}；"
                        f"处理完按协议 status 改 done 并移入 done/）"
                    ),
                    source=MessageSource.SYSTEM,
                    metadata={"interop_source": f.name},  # DSH 借鉴: 注入事件溯源文件名
                ))
            if len(files) > _max_inbox_inject:
                out.insert(0, Message(
                    role="system",
                    content=(
                        f"[外部协调] 另有 {len(files) - _max_inbox_inject} 条待处理消息"
                        f"（超出单轮注入上限 {_max_inbox_inject}，将在后续轮次注入）"
                    ),
                    source=MessageSource.SYSTEM,
                ))
            # EVO-20260817-c35c9178: 重复 notify 自动归档（fail-open，异常仅告警不阻塞注入）
            for f in notify_archives:
                self._archive_interop_notify(f)
            return out
        except Exception:
            logger.warning("协调通道 inbox 扫描失败（fail-open）", exc_info=True)
            return []

    def _archive_interop_notify(self, f: Path) -> None:
        """重复 notify 自动归档: status→done + 移入 done/（EVO-20260817-c35c9178）.

        注入即回显（首见已注入本会话），重复文件不再注入 → 自动归档防堆积。
        fail-open: 任何异常仅告警，文件保留 pending 待人工处理（不静默丢消息）。
        """
        try:
            done_dir = f.parent.parent / "done"
            done_dir.mkdir(parents=True, exist_ok=True)
            txt = f.read_text(encoding="utf-8")
            txt = txt.replace('"status": "pending"', '"status": "done"')
            target = done_dir / f.name
            if target.exists():  # 防覆盖: done 已有同名 → 时间戳后缀
                target = done_dir / f"{f.stem}-{int(time.time())}{f.suffix}"
            target.write_text(txt, encoding="utf-8")
            f.unlink()
        except Exception:  # noqa: BLE001 — 归档失败 fail-open，消息保留待人工处理
            logger.warning(f"notify 自动归档失败（fail-open，保留 pending）: {f.name}", exc_info=True)

    def _inject_interop_messages(
        self, base: list[Message], prefix_len: int, session_id: str = ""
    ) -> tuple[list[Message], int]:
        """装配点调用: inbox 消息注入（返回注入后的 base 与 prefix_len）.

        engine._build_llm_messages 调用（每轮 run 必感知）；任何异常回落原值（fail-open）。
        session_id: 注入目标会话（供 interop.spliced 事件溯源，缺省不记）。

        注入位置（EVO-20260818 cache_window_converge spec §5.3.1-1 c/d，grill-me B1）:
        - 默认尾部追加（env INTEROP_INJECT_TAIL=1，GATE_NOTE 模式）: inbox 存入
          _interop_tail_messages，由 build 在提交末尾追加（转 user）——system+稳定历史
          前缀字节不变，注入轮不断前缀（原实现插在 memory 之后、历史之前 = 前缀区，
          每轮变化即断）。base/prefix_len 原样返回。
        - INTEROP_INJECT_TAIL=0 回退旧行为: 插入 memory 之后、历史之前（2026-08-16 优化）。
        """
        import os

        try:
            inbox = self._interop_inbox_messages()
            if inbox:
                _tail = os.environ.get("INTEROP_INJECT_TAIL", "1") == "1"
                # DSH 借鉴(2026-08-17): interop.spliced 注入事件（对齐 agent/inbox/spliced）——
                # 记录来源/条数/位置，缓存审计可追溯"哪轮请求含外部注入"（fail-open）
                try:
                    self._event_append(
                        session_id or "?",
                        "interop.spliced",
                        {
                            "session_id": session_id or "?",
                            "round": 0,  # 构建期不知轮次，如实置 0
                            "count": len(inbox),
                            "start": prefix_len if not _tail else -1,  # tail 模式无前缀偏移
                            "position": "tail" if _tail else "prefix",
                            "sources": [
                                (m.metadata or {}).get("interop_source", "")
                                for m in inbox
                            ],
                            "content_preview": (inbox[0].content or "")[:200],
                        },
                    )
                except Exception:  # noqa: BLE001 — 注入事件失败 fail-open（不影响注入本身）
                    logger.warning("interop.spliced 事件写入失败（fail-open）")
                if _tail:
                    self._interop_tail_messages = inbox
                    return base, prefix_len
                return base[:prefix_len] + inbox + base[prefix_len:], prefix_len + len(inbox)
        except Exception:
            logger.warning("协调通道 inbox 注入失败（fail-open）", exc_info=True)
        return base, prefix_len
