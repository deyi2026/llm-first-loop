"""投影一致性门闸阶段（EVO-20260817-b6554376；design T5-C 第一批）.

seq（消息数）= 历史追加水印；ver（构建参数+动态输入指纹）= 参数水印；
ver+seq 匹配而 built_hash 不同 → 非确定性构建/历史被改 → 只读告警
（fail-open 不阻断 run）。借鉴 DSH seq 水印。
"""
from __future__ import annotations

import datetime as _dt
import logging
from collections.abc import Callable
from typing import Any

from llm_loop.core.cache_health import GATE_NOTE_CONTENT
from llm_loop.core.history import projection_check, projection_ver, stable_digest
from llm_loop.core.prompt_build.context import BuildDecision

logger = logging.getLogger(__name__)

# 异常 fail-open 哨兵：调用点见此值不更新 _projection_guard_state（保留旧值语义）
GATE_STATE_UNSET = object()


def run_projection_gate(
    *,
    built: list[dict[str, Any]],
    base: list[Any],
    system_prompt: Any,
    prefix_len: int,
    resolved_label: str,
    effective_budget: int,
    sess_anchor: int,
    provider_id: str,
    evidence_manifest_content: Any,
    reasoning_tail: Any,
    settings: Any,
    last_history_compacted: bool,
    sess: Any,
    decision: BuildDecision,
    record_action: Callable[..., Any],
) -> Any:
    """投影门闸（就地更新 sess.projection_guard + decision.compacted）.

    返回 guard state（异常返回 GATE_STATE_UNSET——调用点保持旧状态不更新）。
    """
    try:
        _fp = lambda msgs: stable_digest([(m.role, m.content) for m in msgs])  # noqa: E731
        _settings_fp = stable_digest(
            {
                "tool_tail": getattr(settings, "tool_tail", 0),  # EVO-20260818-f675796c: tail 窗口
                "reasoning_tail": reasoning_tail,
                "skip_injected_system": True,  # spec §5.3.1-5: 推送式注入一律不进提交
                "extract_interval_msgs": getattr(settings, "extract_interval_msgs", 20),
                # Phase5: manifest changes are legitimate projection changes, not nondeterminism.
                "evidence_manifest_fp": stable_digest(evidence_manifest_content),
            }
        )
        # Retired automatic memory/interop/tip channels are not provider-wire inputs and
        # therefore must not perturb the projection version fingerprint.
        _ver = projection_ver(
            model=resolved_label,
            budget=effective_budget,
            anchor=sess_anchor,
            memory_fp=stable_digest([]),
            interop_fp=stable_digest([]),
            system_fp=stable_digest(system_prompt),
            settings_fp=_settings_fp,
        )
        _seq = len(sess.messages)
        # 知情标记剔除: 门闸比较的 built 不含门禁干预注（末尾固定 system 消息）；
        # P1 9.1 聚合后 gate_note 埋入聚合消息（--- [slot:gate_note] --- 段），
        # 含该段的聚合消息整条剔除（近似等价：知情标记不参与投影 hash）
        _c_tail = built[-1].get("content") if built else None
        _built_for_hash = (
            built[:-1]
            if isinstance(_c_tail, str)
            and (
                _c_tail == GATE_NOTE_CONTENT
                or "--- [slot:gate_note] ---" in _c_tail
            )
            else built
        )
        _built_hash = stable_digest(_built_for_hash)
        # EVO-20260817: 压缩轮判定——主动/被动压缩归档（built 消息数 < base）属合法
        # 变化（缓存友好压缩锚点不动 → ver 不变但 built 变短），豁免投影 mismatch 误报
        _compressed_this_build = decision.compacted = (
            bool(last_history_compacted) or len(built) < len(base))
        _guards = sess.projection_guard if sess.projection_guard is not None else {}
        _prev = _guards.get(provider_id)
        _state = projection_check(_prev, ver=_ver, seq=_seq, built_hash=_built_hash)
        if _state == "mismatch" and not _compressed_this_build:
            _hint = (
                f"[投影一致性告警] provider={provider_id} seq={_seq} ver 匹配但构建输出与上次不一致"
                f"——非确定性构建或历史被改（追加式保证被破坏），前缀缓存可能失效（成本放大 ~50 倍）。"
                "只读告警，是否处理由你决定。"
            )
            record_action("run.projection_guard", "mismatch", _hint)
        # 更新缓存行（mismatch 也更新——保留最近构建作新基准，但已告警过）
        _guards[provider_id] = {
            "ver": _ver,
            "seq": _seq,
            "built_hash": _built_hash,
            "ts": _dt.datetime.now(_dt.UTC).isoformat(),
        }
        sess.projection_guard = _guards
        return _state
    except Exception:  # noqa: BLE001 — 门闸失败 fail-open，不阻断 run
        logger.warning("投影一致性门闸异常（fail-open）", exc_info=True)
        return GATE_STATE_UNSET
