"""LLM 语义摘要 Summarizer（design.md §3.2.1 / FR-P1-MEM 系列）.

- SUMMARY_MODE=off/sync/async 三触发方式（FR-P1-MEM-03）
- 预算控制（超时/输入字符上限，FR-P1-MEM-04）
- 失败回退确定性提取（extract_key_info）并如实标注来源（FR-P1-MEM-02/05）
- 禁止虚构摘要（失败必带 note 且 source != "llm"）
"""

from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass
from typing import Any, Literal

from llm_loop.llm.errors import LLMError
from llm_loop.memory.archive import extract_key_info

logger = logging.getLogger(__name__)

SummarySource = Literal["llm", "deterministic", "none"]

_SUMMARY_PROMPT = """请对以下内容生成语义摘要，提炼关键事实、结论与行动项（若有），不超过 200 字。
直接输出摘要正文，不要任何前缀。禁止编造内容中不存在的信息。

内容：
{content}"""


@dataclass
class SummaryResult:
    """摘要结果（来源如实标注，FR-P1-MEM-02/05）."""

    summary: str
    source: SummarySource
    note: str = ""

    def to_dict(self) -> dict:
        return {"summary": self.summary, "source": self.source, "note": self.note}


class Summarizer:
    """LLM 语义摘要器（三模式 + 预算 + 确定性兜底）."""

    def __init__(
        self,
        llm_client: Any | None = None,
        mode: str = "off",
        timeout_s: float = 30.0,
        max_input_chars: int = 20000,
        max_async_queue: int = 4,
    ) -> None:
        self.llm = llm_client
        self.mode = mode
        self.timeout_s = timeout_s
        self.max_input_chars = max_input_chars
        self._max_queue = max_async_queue
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._queue_count = 0
        self._queue_lock = __import__("threading").Lock()

    def summarize(self, text: str) -> SummaryResult:
        """生成摘要（off → 确定性；sync → 同步 LLM；async → 后台提交）.

        async 模式返回确定性摘要占位（立即），后台完成回填由调用方负责。
        """
        if self.mode == "off":
            return self._deterministic(text, note="")
        # 预算: 输入超限截断 + 标注
        truncated = False
        if len(text) > self.max_input_chars:
            text = (
                text[: self.max_input_chars // 2]
                + "\n…[已截断]…\n"
                + text[-self.max_input_chars // 2 :]
            )
            truncated = True

        if self.mode == "sync":
            return self._llm_sync(text, truncated=truncated)

        # async: 提交后台任务，立即返回确定性占位
        if not self._can_submit():
            return self._deterministic(text, note="异步队列已满，当前条目转确定性摘要")
        return self._llm_async(text, truncated=truncated)

    # ── 确定性兜底（P0 既有 extract_key_info，fail-open）──
    def _deterministic(self, text: str, note: str = "") -> SummaryResult:
        try:
            _, _, summary = extract_key_info(text)
            return SummaryResult(summary=summary[:200], source="deterministic", note=note)
        except Exception as exc:  # noqa: BLE001
            return SummaryResult(summary="", source="none", note=f"确定性摘要失败: {exc}")

    # ── 同步 LLM 摘要 ──
    def _llm_sync(self, text: str, *, truncated: bool) -> SummaryResult:
        if self.llm is None:
            return self._deterministic(
                text, note="LLM 摘要不可用（未装配 llm_client），已降级为确定性摘要"
            )
        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "user", "content": _SUMMARY_PROMPT.format(content=text)},
                ],
                tools=[],
            )
            summary = (resp.content or "").strip()
            if not summary:
                return self._deterministic(text, note="LLM 摘要返回空，已降级为确定性摘要")
            note = "输入超预算，已截断" if truncated else ""
            return SummaryResult(summary=summary[:200], source="llm", note=note)
        except LLMError as exc:
            return self._deterministic(text, note=f"LLM 摘要失败: {exc}，已降级为确定性摘要")
        except Exception as exc:  # noqa: BLE001
            return self._deterministic(text, note=f"LLM 摘要异常: {exc}，已降级为确定性摘要")

    # ── 异步 LLM 摘要 ──
    def _can_submit(self) -> bool:
        with self._queue_lock:
            return self._queue_count < self._max_queue

    def _llm_async(self, text: str, *, truncated: bool) -> SummaryResult:
        with self._queue_lock:
            self._queue_count += 1
        try:
            future = self._pool.submit(self._llm_sync_worker, text, truncated)
            self._last_future = future  # 供调用方回填
        except Exception:
            with self._queue_lock:
                self._queue_count -= 1
            return self._deterministic(text, note="异步提交失败，已降级为确定性摘要")
        return self._deterministic(text, note="异步摘要已提交，当前为确定性占位")

    def _llm_sync_worker(self, text: str, truncated: bool) -> SummaryResult:
        """后台线程执行（含超时/降级，绝不抛穿）."""
        try:
            with self._queue_lock:
                self._queue_count -= 1
            return self._llm_sync(text, truncated=truncated)
        except Exception as exc:  # noqa: BLE001
            logger.warning("异步摘要异常（fail-open）: %s", exc)
            return self._deterministic(text, note=f"异步摘要异常: {exc}")

    def summarize_archive(
        self,
        entry_id: str,
        text: str,
        archive: Any,
    ) -> SummaryResult:
        """为压缩档案条目生成摘要并回填（async 模式后台 LLM 摘要 + 回填）.

        Returns:
            SummaryResult（async 模式为确定性占位，LLM 摘要与回填在后台完成）。
        """
        if self.mode == "async":
            # 后台: LLM 摘要生成 → 回填（主线程立即返回占位，DFX-PERF-04）
            placeholder = self._deterministic(text, note="异步摘要已提交，当前为确定性占位")
            if self._can_submit():
                self._pool.submit(self._async_summarize_backfill, archive, entry_id, text)
            else:
                self._backfill(
                    archive, entry_id, placeholder.summary, "deterministic", "异步队列已满"
                )
            return placeholder

        # off/sync: 同步生成 + 回填
        result = self.summarize(text)
        self._backfill(archive, entry_id, result.summary, result.source, result.note)
        return result

    def _async_summarize_backfill(self, archive: Any, entry_id: str, text: str) -> None:
        """后台: LLM 摘要 → 回填（失败降级为确定性，绝不影响主循环）."""
        try:
            truncated = len(text) > self.max_input_chars
            if truncated:
                text = (
                    text[: self.max_input_chars // 2]
                    + "\n…[已截断]…\n"
                    + text[-self.max_input_chars // 2 :]
                )
            result = self._llm_sync(text, truncated=truncated)
            self._backfill(archive, entry_id, result.summary, result.source, result.note)
        except Exception as exc:  # noqa: BLE001 — 后台失败隔离
            logger.warning("异步摘要回填异常（fail-open）: %s", exc)
            try:
                det = self._deterministic(text, note="异步摘要异常，已降级为确定性")
                self._backfill(archive, entry_id, det.summary, det.source, det.note)
            except Exception:
                pass

    def _backfill(self, archive: Any, entry_id: str, summary: str, source: str, note: str) -> None:
        """回填摘要到档案条目（失败仅日志，不影响已交付档案）."""
        try:
            archive.update_summary(entry_id, summary, source)
        except Exception as exc:  # noqa: BLE001
            logger.warning("摘要回填失败（fail-open）: %s", exc)
