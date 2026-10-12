"""前缀稳定性检查器（EVO-20260920-3fb8aa0a 阶段A；纯测量，零行为变更）.

背景: provider 侧 prompt 前缀缓存逐轮失效（成本按全量重复计费）。三处改写源
已定位到函数级（head=core/history.py build_history_messages 预算压缩；
working_set=core/episode_history.py project_active_tool_working_set_with_stats；
tail=core/recent_continuity.py apply_recent_continuity_suffix），但既有
projection_gate（prompt_build/stages/projection_gate.py）只校验整幅视图水印
（ver+seq+built_hash），"前缀在哪一轮、被哪个阶段打破"不可归因。

方案（阶段A）: 每轮在管线三个检查点（ingress_resolution: head/working_set，
tail_assembly: final）对消息列表做逐条指纹（role+content sha256 前 16 位），
与上一轮同检查点指纹求最长公共前缀（LCP）。final LCP ≈ 本轮可复用缓存深度；
按管线序首个 LCP == final LCP 的检查点为改写引入点（启发式归因；全量
stage_lcp 随日志输出，供人工复核）。

硬约束: 纯测量零行为变更——不修改消息列表、不改变门闸判定、不进 Session
schema/持久化；状态仅存进程内（重启后首轮记 cold_baseline）。全路径
fail-open：任何异常只记 debug 日志，不阻断构建。
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

STAGES: tuple[str, ...] = ("head", "working_set", "final")
_FINGERPRINT_CHARS = 16
_MAX_MSGS = 4000
_TRACKER_CAP = 64


def _msg_fingerprint(message: Any) -> tuple[str, int]:
    """返回 (role+content 指纹, content 字符数)；兼容 dict 与属性对象。"""
    role = getattr(message, "role", None)
    content = getattr(message, "content", None)
    if role is None and isinstance(message, dict):
        role = message.get("role")
    if content is None and isinstance(message, dict):
        content = message.get("content")
    role_s = "" if role is None else str(role)
    content_s = "" if content is None else str(content)
    digest = hashlib.sha256(f"{role_s}\x00{content_s}".encode("utf-8", "replace")).hexdigest()
    return digest[:_FINGERPRINT_CHARS], len(content_s)


def _lcp_count(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


@dataclass
class PrefixReport:
    """单轮前缀稳定性测量结果（只读观测，不驱动任何行为）。"""

    session_id: str
    provider_id: str
    verdict: str  # cold_baseline | stable_append | prefix_broken | compressed
    final_lcp_msgs: int = 0
    final_cached_chars: int = 0  # 上一轮 final 前 lcp 条的字符量（≈可复用缓存深度）
    prev_final_msgs: int = 0
    curr_final_msgs: int = 0
    stage_lcp: dict[str, int] = field(default_factory=dict)
    attribution: str = ""  # 管线序首个 LCP==final 的检查点；空=无破坏/不可归因
    compressed_round: bool = False

    def summary(self) -> str:
        stages = ",".join(f"{k}={v}" for k, v in self.stage_lcp.items())
        return (
            f"provider={self.provider_id} verdict={self.verdict} "
            f"final_lcp={self.final_lcp_msgs}/{self.curr_final_msgs}"
            f"(prev={self.prev_final_msgs},cached_chars={self.final_cached_chars}) "
            f"stage_lcp[{stages}] attribution={self.attribution or '-'} "
            f"compressed={str(self.compressed_round).lower()}"
        )


class _PrefixStabilityTracker:
    """单 (session, provider) 的跨轮指纹基线（仅进程内，不持久化）。"""

    def __init__(self) -> None:
        self._prev: dict[str, tuple[list[str], list[int]]] = {}
        self._current: dict[str, tuple[list[str], list[int]]] = {}

    def observe(self, stage: str, msgs: Any) -> None:
        if stage not in STAGES:
            return
        fps: list[str] = []
        lens: list[int] = []
        for message in list(msgs or [])[:_MAX_MSGS]:
            digest, length = _msg_fingerprint(message)
            fps.append(digest)
            lens.append(length)
        self._current[stage] = (fps, lens)

    def finalize(
        self, *, compressed: bool, session_id: str, provider_id: str
    ) -> PrefixReport | None:
        try:
            curr_final = self._current.get("final")
            if curr_final is None:
                return None  # 无 final 检查点（构建中途异常等）——不做对比
            prev_final = self._prev.get("final")
            if prev_final is None:
                return PrefixReport(
                    session_id=session_id,
                    provider_id=provider_id,
                    verdict="cold_baseline",
                    prev_final_msgs=0,
                    curr_final_msgs=len(curr_final[0]),
                    compressed_round=compressed,
                )
            lcp = _lcp_count(prev_final[0], curr_final[0])
            stage_lcp: dict[str, int] = {}
            for stage in STAGES:
                prev_stage = self._prev.get(stage)
                curr_stage = self._current.get(stage)
                if prev_stage is not None and curr_stage is not None:
                    stage_lcp[stage] = _lcp_count(prev_stage[0], curr_stage[0])
            if compressed:
                verdict, attribution = "compressed", ""
            elif lcp < min(len(prev_final[0]), len(curr_final[0])):
                verdict = "prefix_broken"
                attribution = next((s for s in STAGES if stage_lcp.get(s) == lcp), "")
            else:
                verdict, attribution = "stable_append", ""
            return PrefixReport(
                session_id=session_id,
                provider_id=provider_id,
                verdict=verdict,
                final_lcp_msgs=lcp,
                final_cached_chars=sum(prev_final[1][:lcp]),
                prev_final_msgs=len(prev_final[0]),
                curr_final_msgs=len(curr_final[0]),
                stage_lcp=stage_lcp,
                attribution=attribution,
                compressed_round=compressed,
            )
        finally:
            self._prev = self._current
            self._current = {}


_TRACKERS: dict[tuple[str, str], _PrefixStabilityTracker] = {}
_TRACKERS_LOCK = threading.Lock()


def _tracker_for(session_id: str, provider_id: str) -> _PrefixStabilityTracker:
    key = (str(session_id or ""), str(provider_id or ""))
    with _TRACKERS_LOCK:
        tracker = _TRACKERS.pop(key, None)
        if tracker is None:
            tracker = _PrefixStabilityTracker()
        _TRACKERS[key] = tracker  # 重插即 LRU touch
        while len(_TRACKERS) > _TRACKER_CAP:
            _TRACKERS.pop(next(iter(_TRACKERS)))
        return tracker


def observe_checkpoint(session_id: str, provider_id: str, stage: str, msgs: Any) -> None:
    """阶段A检查点：记录本轮该阶段的消息指纹（纯测量；内部 fail-open）。"""
    try:
        _tracker_for(session_id, provider_id).observe(stage, msgs)
    except Exception:  # noqa: BLE001 — 纯测量 fail-open
        logger.debug("prefix_stability observe failed", exc_info=True)


def finalize_round(
    session_id: str,
    provider_id: str,
    *,
    compressed: bool = False,
    record_action: Any = None,
) -> PrefixReport | None:
    """跨轮对比并输出归因报告（纯测量；内部 fail-open，绝不阻断构建）。"""
    try:
        report = _tracker_for(session_id, provider_id).finalize(
            compressed=compressed, session_id=session_id, provider_id=provider_id
        )
    except Exception:  # noqa: BLE001 — 纯测量 fail-open
        logger.debug("prefix_stability finalize failed", exc_info=True)
        return None
    if report is None:
        return None
    try:
        logger.info("[prefix_stability] %s", report.summary())
        if record_action is not None:
            record_action("run.prefix_stability", report.verdict, report.summary())
    except Exception:  # noqa: BLE001 — 观测输出 fail-open
        logger.debug("prefix_stability report emission failed", exc_info=True)
    return report
