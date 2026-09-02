"""InteropService——协调通道 inbox 注入职责服务（R9-B5-W4-02e：_InteropMixin 退役；宿主面显式经 self._host 标注，沿 archive 惯例）. 原理（RULE-AI-14 实现层，2026-08-16）:

程序级自动感知: DSH→LFL 待处理消息由 runtime 扫描。R8.13 起 notify/backlog 与
coordinate/task 均只进入 interop UI/action 状态；外部内容必须经未来的用户输入侧
“接受/插入”动作显式授权后，才可升级为模型输入。
协议见 data/interop/INTEROP.md。

设计要点:
- 扫描 inbox 不触发额外 run、不占会话锁；notify 可自动归档 done，coordinate/task 保持 pending 等待用户处理
- runtime 不构造外部协调 system/user prompt；不猜当前会话/任务，不把外部指令伪装成用户输入
- 不打 injected_system 标记: 该标记在本地 provider 下会被 skip 跳过提交——
  协调待办是核心消息，所有 provider 均须可见
- 注入位置在 memory 之后、历史之前（P1-10 前缀稳定）: system_prompt+memory
  段在有/无消息轮字节级一致，服务端前缀缓存命中不因 inbox 存在与否而失配；
  仅 history 段起点随消息轮偏移（低频、量小、单轮，锚点换算已计入）
- fail-open: 目录缺失/读失败/格式坏 → 跳过，异常返回空（不阻塞主流程）
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (02e 迁移保留: 动态宿主槽位属性静态不可解析，文件级关闭这两条——宿主态所有权在 LoopEngine)


from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from llm_loop.core.message import Message

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)

_INTEROP_INBOX_REL = Path("interop") / "lfl_to_dsh" / "pending"


class InteropService:
    """协调通道（RULE-AI-14）程序级注入."""

    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def _interop_inbox_messages(self) -> list[Message]:
        """扫描协调通道 inbox；返回值仅为兼容形状，R8.13 live path 恒为空.

        基准路径: LFL_DATA_DIR/interop/lfl_to_dsh/pending（与 web/routes.py 一致）。
        notify 自动归档到 done；coordinate/task 保持 pending 并仅记录 observability。
        任何外部正文都不会由 runtime 自动升级为模型 prompt。

        R8.12/E25 notify/backlog prompt exit:
        - topic=notify（job completion/subagent/scheduler 普通提醒）直接归档到 done/，
          保留 Web interop UI + action/event 可见性，但不构造 Message、不进入 provider prompt；
        - 同指纹 notify 仍幂等归档，不会因重复文件重新获得 prompt authority；
        - pending backlog 只记录结构化 action/watchdog 状态，不再构造“另有 N 条”提示；
        - R8.13/E26: coordinate/task 也退出自动 prompt；不消费文件，等待用户在输入侧明确接受/插入。
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
            seen = getattr(self._host, "_notify_injected", None)
            if seen is None:
                if self._host is None:
                    # 02e 服务化：tests 以 host=None 裸服务直构造验证 fail-open
                    # 契约（沿 mixin 时代裸实例语义）——dedupe 集合落服务实例
                    seen = self._notify_injected = set()
                else:
                    seen = self._host._notify_injected = set()
            for f in files[-_max_inbox_inject:]:
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    # EVO-20260825 任务9（§5.4.1-5）: 解析失败 → 隔离到 dead/ + ERROR
                    # （原实现静默跳过——损坏文件长期滞留堆积，阻塞消费诊断）
                    self._quarantine_interop_bad(f)
                    continue
                if d.get("status") != "pending":
                    continue
                body = str(d.get("body", "")).strip()
                if not body:
                    continue
                if d.get("topic") == "notify":
                    fp = (str(d.get("from", "")), str(d.get("ref", "")), body)
                    duplicate = fp in seen
                    seen.add(fp)
                    # R8.12/E25: notification is user/runtime state, never model input.
                    # Move it to done/ so Web UI/retrieval keeps the body instead of hiding it
                    # in processed/, then emit only compact structured action telemetry.
                    if self._archive_interop_notify(f):
                        try:
                            action = getattr(self._host, "_record_action", None)
                            if callable(action):
                                action(
                                    "interop.notify",
                                    "duplicate_archived" if duplicate else "observed_only",
                                    f"id={d.get('id', f.stem)};from={d.get('from', '')};"
                                    f"ref={d.get('ref', '')};prompt_chars=0",
                                )
                        except Exception:  # noqa: BLE001 — archive is authoritative
                            logger.debug("interop notify action trace 失败（忽略）", exc_info=True)
                    continue
                # R8.13/E26: external coordinate/task is not user-authorized input.
                # Keep the file pending for Web/UI inspection and future explicit input-side
                # acceptance; record only one compact observation per process/file.
                topic = str(d.get("topic", "") or "")
                observed = getattr(self._host, "_interop_external_observed", None)
                if observed is None:
                    if self._host is None:
                        # 02e 服务化：裸服务（host=None）同 L74 fail-open 守卫
                        observed = self._interop_external_observed = set()
                    else:
                        observed = self._host._interop_external_observed = set()
                if f.name not in observed:
                    observed.add(f.name)
                    try:
                        action = getattr(self._host, "_record_action", None)
                        if callable(action):
                            action(
                                "interop.external_input",
                                "awaiting_user_authorization",
                                f"id={d.get('id', f.stem)};topic={topic};from={d.get('from', '')};"
                                f"ref={d.get('ref', '')};prompt_chars=0",
                            )
                    except Exception:  # noqa: BLE001 — observability only
                        logger.debug("interop external action trace 失败（忽略）", exc_info=True)
                continue
            if len(files) > _max_inbox_inject:
                # R8.12/E25: queue depth is runtime observability, not task semantics.
                # InboxWatcher also diagnoses backlog; this action gives build-time evidence
                # without spending prompt characters or distracting the model.
                try:
                    action = getattr(self._host, "_record_action", None)
                    if callable(action):
                        action(
                            "interop.pending_backlog",
                            "observed_only",
                            f"pending={len(files)};scan_limit={_max_inbox_inject};prompt_chars=0",
                        )
                except Exception:  # noqa: BLE001 — observability only
                    logger.debug("interop backlog action trace 失败（忽略）", exc_info=True)
            return out
        except Exception:
            logger.warning("协调通道 inbox 扫描失败（fail-open）", exc_info=True)
            return []

    def _consume_interop_file(self, f: Path) -> bool:
        """EVO-20260825 任务9（§5.4.1-4）: 原子化消费——移动到 processed/（按日期分目录）.

        Path.rename() 本地文件系统原子；已被并发消费/竞态（FileNotFoundError）→
        返回 False（调用方跳过，幂等）；移动成功 → True（内容已读入内存，随调用方注入）。
        """
        try:
            day = time.strftime("%Y%m%d")
            target_dir = f.parent / "processed" / day
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f.name
            if target.exists():  # 防覆盖: processed 已有同名 → 时间戳后缀
                target = target_dir / f"{f.stem}-{int(time.time())}{f.suffix}"
            f.rename(target)
            return True
        except FileNotFoundError:
            return False  # 已被消费（竞态）→ 幂等跳过
        except OSError:
            logger.warning("协调 pending 消费移动失败（fail-open，跳过该条）: %s", f.name)
            return False

    def _quarantine_interop_bad(self, f: Path) -> None:
        """EVO-20260825 任务9（§5.4.1-5）: 解析失败的 pending 文件隔离到 dead/ + ERROR.

        不静默跳过（原实现长期滞留堆积），隔离保留审计追溯。
        """
        try:
            dead_dir = f.parent / "dead"
            dead_dir.mkdir(parents=True, exist_ok=True)
            target = dead_dir / f.name
            if target.exists():
                target = dead_dir / f"{f.stem}-{int(time.time())}{f.suffix}"
            f.rename(target)
            logger.error("协调 pending 解析失败，已隔离到 dead/: %s", f.name)
        except OSError:
            logger.warning("协调 pending 坏文件隔离失败（fail-open，保留原位）: %s", f.name)

    def _archive_interop_notify(self, f: Path) -> bool:
        """Archive notify to user-visible ``done/`` without granting prompt authority.

        R8.12/E25 applies this to first-seen and duplicate notify alike.  The JSON body is
        preserved for Web/retrieval, only ``status`` becomes ``done``.  On failure the file
        remains pending and the caller can retry on a later scan; no silent data loss.
        """
        try:
            done_dir = f.parent.parent / "done"
            done_dir.mkdir(parents=True, exist_ok=True)
            payload = json.loads(f.read_text(encoding="utf-8"))
            payload["status"] = "done"
            target = done_dir / f.name
            if target.exists():  # 防覆盖: done 已有同名 → 时间戳后缀
                target = done_dir / f"{f.stem}-{int(time.time())}{f.suffix}"
            target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            f.unlink()
            return True
        except Exception:  # noqa: BLE001 — 归档失败 fail-open，消息保留待人工处理
            logger.warning("notify 自动归档失败（fail-open，保留 pending）: %s", f.name, exc_info=True)
            return False

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
            # R8.13/E26: pre-upgrade err1210 defer state may still hold interop frames in
            # memory. Retire them here rather than allowing historical external prose to
            # regain prompt authority after the live producer has been disabled.
            legacy_tail = getattr(self._host, "_interop_tail_messages", None) or []
            if legacy_tail:
                self._host._interop_tail_messages = None
                refs = list(getattr(self._host, "_deferred_replay_refs", None) or [])
                self._host._deferred_replay_refs = [
                    (slot, ref) for slot, ref in refs if str(slot) != "interop"
                ]
                try:
                    self._host._record_action(
                        "interop.external_input",
                        "legacy_defer_retired",
                        f"count={len(legacy_tail)};prompt_chars=0",
                    )
                except Exception:  # noqa: BLE001 — observability only
                    logger.debug("interop legacy defer retire trace 失败（忽略）", exc_info=True)
            inbox = self._interop_inbox_messages()
            if inbox:
                _tail = os.environ.get("INTEROP_INJECT_TAIL", "1") == "1"
                # DSH 借鉴(2026-08-17): interop.spliced 注入事件（对齐 agent/inbox/spliced）——
                # 记录来源/条数/位置，缓存审计可追溯"哪轮请求含外部注入"（fail-open）
                try:
                    self._host._event_append(
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
                    self._host._interop_tail_messages = inbox
                    return base, prefix_len
                return base[:prefix_len] + inbox + base[prefix_len:], prefix_len + len(inbox)
        except Exception:
            logger.warning("协调通道 inbox 注入失败（fail-open）", exc_info=True)
        return base, prefix_len

    # ── 2026-08-20 (DESIGN-v3 v2 落地): 切换通知注入（AI 主导上下文选择第一步）──
    # 2026-08-27 自 engine.py 迁入（M53 行数守卫: engine 拆分评审——err1210 P0 接线
    # 净增后超出预算，按守卫指引将职责就近下沉；行为逐行一致，仅 fail-open 日志
    # 改用本模块 logger）。
    def _inject_switch_notice(self, switch_from: str, switch_to: str, sess=None) -> None:
        """Record a provider/model transition without creating prompt material.

        Routing state is runtime observability, not a user instruction.  R8.8 removes
        the historical chat-text replay/"continue current task" notice entirely; active
        task continuity must come from canonical task state or on-demand retrieval.
        """
        try:
            if not switch_from or not switch_to or switch_from == switch_to:
                return
            self._host._record_action(
                "model.switch",
                "observed",
                f"{switch_from}->{switch_to}",
            )
        except Exception:  # noqa: BLE001 — observability must not block routing
            logger.debug("模型切换审计记录异常（fail-open）", exc_info=True)
