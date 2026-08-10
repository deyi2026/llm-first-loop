"""独立记忆提取 MemoryExtractor（design.md §3.3 / FR-P1-EXT 系列）.

边界说明（M11）: 本模块为独立提取调度器（触发时机/预算/异步/审计）;记忆块解析纯函数在 memory/extract.py（被复用）。

- 三触发: 会话结束（session_end）/ 定期（interval）/ 手动（manual）
- 输出与即时 [[memory]] 沉淀完全同构（复用 memory/extract.py）
- 内容指纹去重（与既有条目共存不重复）
- 异步失败隔离（不阻塞主循环）；预算/频次冷却；审计落盘可检索
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from llm_loop.memory.extract import extract_memory_blocks, memory_blocks_to_entries
from llm_loop.memory.store import MemoryEntry, MemoryStore

logger = logging.getLogger(__name__)

ExtractTrigger = Literal["session_end", "interval", "manual"]

_EXTRACT_PROMPT = """从以下会话历史中提取值得长期记忆的信息（关键事实/决策/约定），
以结构化记忆块输出（与常规记忆块格式一致），每块一个条目，无值得记忆内容则输出空：

[[memory]] {{"type": "fact", "content": "要记住的内容", "keywords": ["关键词"]}} [[/memory]]

会话历史：
{history}"""


@dataclass
class ExtractRecord:
    """一次独立提取执行记录（FR-P1-EXT-06，落盘可检索）."""

    ts: str
    session_id: str
    trigger: ExtractTrigger
    input_scope: str
    input_chars: int
    entries: int
    failures: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "session_id": self.session_id,
            "trigger": self.trigger,
            "input_scope": self.input_scope,
            "input_chars": self.input_chars,
            "entries": self.entries,
            "failures": self.failures,
            "note": self.note,
        }


@dataclass
class ExtractResult:
    """提取执行结果."""

    records: list[ExtractRecord]
    entries: list[MemoryEntry]
    skipped_duplicates: int = 0


def _fingerprint(content: str) -> str:
    """内容规范化 SHA-256（去空白/标点）用于去重."""
    norm = re.sub(r"[\s\W_]+", "", content.lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


class MemoryExtractor:
    """独立记忆提取器（三触发 + 去重 + 预算冷却 + 异步隔离 + 审计）."""

    def __init__(
        self,
        llm_client: Any | None = None,
        memory: MemoryStore | None = None,
        session_store: Any | None = None,
        *,
        enabled: bool = True,
        interval_msgs: int = 20,
        cooldown_s: float = 600.0,
        max_input_chars: int = 100000,
        timeout_s: float = 60.0,
        audit_dir: str | Path | None = None,
    ) -> None:
        self.llm = llm_client
        self.memory = memory
        self.session_store = session_store
        self.enabled = enabled
        self.interval_msgs = interval_msgs
        self.cooldown_s = cooldown_s
        self.max_input_chars = max_input_chars
        self.timeout_s = timeout_s
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._last_trigger_ts: dict[str, float] = {}
        self._lock = threading.Lock()

    # ── 触发判定 ──
    def maybe_trigger(self, session_id: str) -> bool:
        """定期触发判定（消息数 ≥ 阈值 且 过冷却 → 异步执行）.

        Returns:
            True 已提交异步提取；False 未满足（不产生审计噪音）。
        """
        if not self.enabled or self.session_store is None:
            return False
        meta = self.session_store.get_meta(session_id)
        if meta is None:
            return False
        now = time.monotonic()
        with self._lock:
            last = self._last_trigger_ts.get(session_id, 0.0)
            if meta.message_count < self.interval_msgs or (now - last) < self.cooldown_s:
                return False
            self._last_trigger_ts[session_id] = now
        self._run_async(session_id, trigger="interval")
        return True

    def extract_session(self, session_id: str, trigger: ExtractTrigger = "manual") -> ExtractResult:
        """同步提取（会话结束/手动，受预算与冷却约束）."""
        if not self.enabled:
            return ExtractResult(records=[], entries=[], skipped_duplicates=0)
        if self.session_store is None or self.llm is None or self.memory is None:
            self._audit(session_id, trigger, "不可用", 0, ["组件未装配"], note="提取不可用")
            return ExtractResult(records=[], entries=[], skipped_duplicates=0)

        session = self.session_store.load(session_id)
        # 预算: 输入超限截断最旧 + 标注
        history_text = self._build_history_text(session.messages)
        note = ""
        if len(history_text) > self.max_input_chars:
            history_text = history_text[: self.max_input_chars]
            note = f"输入超预算，已截断至 {self.max_input_chars} 字符"

        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "user", "content": _EXTRACT_PROMPT.format(history=history_text)}
                ],
                tools=[],
            )
            answer = resp.content or ""
        except Exception as exc:  # noqa: BLE001 — 提取失败隔离，不影响主循环
            self._audit(
                session_id,
                trigger,
                "会话全量",
                len(history_text),
                [f"提取调用失败: {exc}"],
                note="提取失败",
            )
            return ExtractResult(records=[], entries=[], skipped_duplicates=0)

        # 解析（与即时沉淀同构）
        blocks = extract_memory_blocks(answer)
        entries, failures = memory_blocks_to_entries(
            blocks, session_id=session_id, message_id="extract"
        )
        # 指纹去重 + deposit_path=extract
        new_entries: list[MemoryEntry] = []
        skipped = 0
        existing_fps = {e.content_fingerprint for e in self.memory.all() if e.content_fingerprint}
        for e in entries:
            fp = _fingerprint(e.content)
            e.content_fingerprint = fp
            e.deposit_path = "extract"
            if fp in existing_fps:
                skipped += 1
                continue
            existing_fps.add(fp)
            new_entries.append(e)
            self.memory.save_entry(e)

        self._audit(
            session_id,
            trigger,
            f"会话全量（消息数 {len(session.messages)}）",
            len(history_text),
            failures,
            note=note,
        )
        return ExtractResult(
            records=[self._last_record(session_id)],
            entries=new_entries,
            skipped_duplicates=skipped,
        )

    # ── 异步执行（失败隔离）──
    def _run_async(self, session_id: str, trigger: ExtractTrigger) -> None:
        def worker() -> None:
            try:
                self.extract_session(session_id, trigger=trigger)
            except Exception as exc:  # noqa: BLE001 — 异步失败隔离，不影响主循环
                logger.warning("异步独立提取异常（fail-open）: %s", exc)
                self._audit(
                    session_id, trigger, "会话全量", 0, [f"异步异常: {exc}"], note="提取失败"
                )

        threading.Thread(target=worker, daemon=True).start()

    # ── 辅助 ──
    def _build_history_text(self, messages: list[Any]) -> str:
        lines = []
        for m in messages:
            role = m.role
            content = m.content[:500]
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _audit(
        self,
        session_id: str,
        trigger: str,
        input_scope: str,
        input_chars: int,
        failures: list[str],
        note: str = "",
        entries: int = 0,
    ) -> None:
        """审计落盘（FR-P1-EXT-06，可被 search_records kind=memory_extract 检索）."""
        if self._audit_dir is None:
            return
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            record = ExtractRecord(
                ts=datetime.now(UTC).isoformat(),
                session_id=session_id,
                trigger=trigger,  # type: ignore[arg-type]
                input_scope=input_scope,
                input_chars=input_chars,
                entries=entries,
                failures=failures,
                note=note,
            )
            with (self._audit_dir / "memory_extract_log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
            self._last_record_store = record
        except OSError:
            pass  # fail-open

    def _last_record(self, session_id: str) -> ExtractRecord:
        return getattr(self, "_last_record_store", None) or ExtractRecord(
            ts="", session_id=session_id, trigger="manual", input_scope="", input_chars=0, entries=0
        )
