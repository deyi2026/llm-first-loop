"""TASK-ac085ab1-002 P0 模型收尾: knowledge_read 打点、待结算清单与批量结算回执.

设计来源: docs/LFL 任务知识使用反馈与检索闭环设计草案.md v3（「待结算清单的
生成机制」「收尾可靠性与操作成本」「边界与失败模式决策表」）。

机制（全部机械、fail-open，不新增硬阻断门）：

- 读取事实来自单一打点：统一检索工具的精确水合成功路径追加 ``knowledge.read``
  事件（设计文档称 knowledge_read 事件），携带 kind、稳定 ref、返回版本哈希、
  session、run；版本哈希取自构成本次回执的同一份内存内容快照，打点时不重新
  读盘。事件语义收窄为"精确内容已返回调用方"——不证明已送达模型输入、更不
  证明模型已采用。泛查询不打点。
- 待结算清单 = 读取事件 − 持久化结算回执，按（工作单元、对象、读取版本）
  三元组匹配；清单自带覆盖边界声明（不覆盖 read_file 直读知识文件、附件内嵌
  摘录、泛查询命中）。knowledge_read 缺失时退回工具迹扫描并标注非权威
  （仅 ref、版本 unknown）。无接触拆两列呈现：事件源无接触 / 模型自报无接触。
- 批量结算逐条 receipt（committed / pending / failed）：条目缺 ref、决定非法、
  ref 不存在 → failed 并给原因，整批其余条目继续；写入结果未知（durability
  uncertain）→ pending，附"先按 submission_hash 查原结算"提示，不谎报成功。
- 结算成本自 P0 入回执：结算调用次数与结算占用回合数（按 run 去重）。
- 归属不明 → attribution=unresolved：不抵扣任何确定任务的待结算项。
- 规则侧回执写 canonical EventStore（``rule.feedback`` 事件，按 submission_hash
  去重）；规则反馈注释通道经 RuleFeedbackProjection 从事件投影取数。
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from llm_loop.use_ledger import derive_slot_id, derive_submission_hash

logger = logging.getLogger(__name__)

# 设计文档 v3 称 "knowledge_read 事件"；事件类型命名沿用仓库 dotted 惯例。
KNOWLEDGE_READ_EVENT_TYPE = "knowledge.read"
RULE_FEEDBACK_EVENT_TYPE = "rule.feedback"

KNOWLEDGE_READ_SCHEMA = "knowledge-read/v1"
RULE_FEEDBACK_SCHEMA = "rule-feedback/v1"

COVERAGE_BOUNDARY = (
    "事件源可观测范围=统一检索工具精确水合成功路径（knowledge_read 事件）；"
    "不覆盖 read_file 直读知识文件、附件内嵌摘录、泛查询命中。"
    "清单是事件源可观测范围，不是全部知识接触；模型可补充自报条目（self_reported）。"
)

_KNOWN_KINDS = {"method", "experience", "lesson", "rule"}
_DECISIONS = {"applied", "adapted", "not_applicable", "rejected"}
_BENEFITS = {"helped", "neutral", "hindered", "unknown", "mixed"}
_LEVELS = {"model_declared", "observation_linked", "independently_evaluated"}
_RULE_REF_RE = re.compile(r"^RULE-AI-\d+(?:\.\d+)?$", re.IGNORECASE)


@dataclass(frozen=True)
class SettlementItem:
    """一条结算提交（模型只给字段值，两层键由程序派生）."""

    kind: str
    ref: str
    decision: str = ""
    benefit: str = "unknown"
    evidence_level: str = "model_declared"
    evidence_refs: tuple[str, ...] = ()
    note: str = ""
    suggestion: str = ""
    supersedes: str = ""
    read_version: str = ""
    self_reported: bool = False


def emit_knowledge_read(
    sink: Callable[[dict], None] | None,
    *,
    kind: str,
    ref: str,
    version: str,
    session_id: str,
    run: str = "",
) -> None:
    """fail-open 打点：任何失败只降级为不打点，绝不影响检索主路径."""
    if sink is None or not ref or not version:
        return
    try:
        sink(
            {
                "schema": KNOWLEDGE_READ_SCHEMA,
                "kind": str(kind),
                "ref": str(ref),
                "version": str(version),
                "session_id": str(session_id or ""),
                "run": str(run or ""),
                "semantics": "exact_content_returned_to_caller",
            }
        )
    except Exception:  # noqa: BLE001 — 打点 fail-open
        logger.debug("knowledge_read 打点失败（fail-open）", exc_info=True)


# ── 读取事实与回执收集 ──


def _iter_events(event_store: Any, session_id: str) -> list[dict]:
    """读取会话事件并展开为机械 dict（payload 合并顶层键）."""
    try:
        events = event_store.read(session_id)
    except Exception:  # noqa: BLE001 — fail-open
        return []
    rows: list[dict] = []
    for event in events or []:
        try:
            payload = dict(getattr(event, "payload", {}) or {})
            row = {
                "type": str(getattr(event, "type", "") or ""),
                "ts": str(getattr(event, "ts", "") or ""),
                "seq": int(getattr(event, "seq", 0) or 0),
            }
            row.update({k: v for k, v in payload.items()})
            rows.append(row)
        except Exception:  # noqa: BLE001
            continue
    return rows


def collect_knowledge_reads(event_store: Any, session_id: str) -> list[dict]:
    """收集会话内全部 knowledge.read 读取事实（旧→新）."""
    return [
        row
        for row in _iter_events(event_store, session_id)
        if row.get("type") == KNOWLEDGE_READ_EVENT_TYPE
    ]


def collect_rule_feedback_receipts(event_store: Any, session_id: str) -> list[dict]:
    """收集会话内全部规则结算回执（旧→新）."""
    return [
        row
        for row in _iter_events(event_store, session_id)
        if row.get("type") == RULE_FEEDBACK_EVENT_TYPE
    ]


def _ledger_receipts(store: Any) -> list[dict]:
    """读取一侧 usage ledger 的 v2 结算回执（fail-open）."""
    if store is None:
        return []
    try:
        entries = store.usage_entries()
    except TypeError:
        try:
            entries = store.usage_entries("")
        except Exception:  # noqa: BLE001
            return []
    except Exception:  # noqa: BLE001
        return []
    return [e for e in entries if isinstance(e, dict) and e.get("submission_hash")]


def _receipt_ref(entry: dict) -> str:
    return str(entry.get("method_ref") or entry.get("experience_ref") or entry.get("ref") or "")


def _receipt_version(entry: dict) -> str:
    return str(entry.get("read_version") or "")


def _receipt_work_unit(entry: dict) -> str:
    return str(entry.get("work_unit_id") or "")


def _receipts_for_session(
    method_store: Any, experience_store: Any, event_store: Any, session_id: str
) -> list[dict]:
    receipts = _ledger_receipts(method_store) + _ledger_receipts(experience_store)
    receipts += collect_rule_feedback_receipts(event_store, session_id)
    return receipts


def _offsets(read: dict, receipts: list[dict], *, work_unit_id: str, session_id: str) -> bool:
    """回执是否抵扣该读取事实：工作单元×对象×读取版本三元组匹配.

    确定任务窗口：跳过 attribution=unresolved 的回执（降级窗口回执不抵扣
    确定任务，也不进任务级覆盖率分母）。
    """
    for entry in receipts:
        if _receipt_ref(entry) != str(read.get("ref") or ""):
            continue
        if _receipt_version(entry) != str(read.get("version") or ""):
            continue
        if work_unit_id:
            if _receipt_work_unit(entry) != work_unit_id:
                continue
            if str(entry.get("attribution") or "") == "unresolved":
                continue
        else:
            # 降级 session 窗口：会话内回执即可抵扣（含其他降级回执）
            if str(entry.get("session_id") or "") and str(entry.get("session_id")) != session_id:
                continue
        return True
    return False


def build_pending_settlement(
    *,
    event_store: Any,
    method_store: Any = None,
    experience_store: Any = None,
    session_id: str,
    work_unit_id: str = "",
    tool_trace: Iterable[Any] | None = None,
    model_self_reported_no_contact: bool = False,
) -> dict:
    """待结算清单 = 读取事件 − 持久化结算回执（fail-open 投影，非新账本）."""
    wu = str(work_unit_id or "").strip()
    reads = collect_knowledge_reads(event_store, session_id)
    read_source = "knowledge_read_events"
    items: list[dict] = []
    # P1-3：读取事件先按唯一键 (kind, ref, version) 收敛——settled_count 的单位是
    # "被回执抵扣的唯一键数"，同 key 重复读取不得虚增已结算数。
    read_keys: set[tuple[str, str, str]] = {
        (str(r.get("kind") or ""), str(r.get("ref") or ""), str(r.get("version") or ""))
        for r in reads
    }

    if reads:
        receipts = _receipts_for_session(method_store, experience_store, event_store, session_id)
        pending: dict[tuple[str, str, str], dict] = {}
        for read in reads:
            if _offsets(read, receipts, work_unit_id=wu, session_id=session_id):
                continue
            key = (str(read.get("kind") or ""), str(read.get("ref") or ""), str(read.get("version") or ""))
            slot = pending.setdefault(
                key,
                {
                    "kind": key[0],
                    "ref": key[1],
                    "read_version": key[2],
                    "last_read_ts": str(read.get("ts") or ""),
                    "source": "knowledge_read_events",
                    "self_reported": False,
                },
            )
            if str(read.get("ts") or "") > slot["last_read_ts"]:
                slot["last_read_ts"] = str(read.get("ts") or "")
        items = list(pending.values())
    elif tool_trace is not None:
        # 降级线索：工具迹扫描（仅 ref、版本 unknown、非权威，不用于版本级抵扣）
        from llm_loop.core.loop.engine_services.method_injection import scan_method_use_ledger

        try:
            ledger = scan_method_use_ledger(list(tool_trace))
        except Exception:  # noqa: BLE001
            ledger = None
        if ledger is not None:
            read_source = "tool_trace_non_authoritative"
            seen: set[str] = set()
            for ref in ledger.hydrated:
                clean = str(ref or "").strip()
                if not clean or clean in seen:
                    continue
                seen.add(clean)
                items.append(
                    {
                        "kind": "method",
                        "ref": clean,
                        "read_version": "unknown",
                        "last_read_ts": "",
                        "source": "tool_trace_non_authoritative",
                        "self_reported": False,
                    }
                )

    return {
        "work_unit_id": wu,
        "attribution": f"task({wu})" if wu else "degraded(session)",
        "coverage_boundary": COVERAGE_BOUNDARY,
        "read_source": read_source,
        "window": {
            "anchor": "session_reads_minus_receipts",
            "session_id": str(session_id or ""),
        },
        "items": items,
        "settled_count": max(0, len(read_keys) - len(items)) if reads else 0,
        "none_columns": {
            "event_source_no_contact": not reads and not items,
            "model_self_reported_no_contact": bool(model_self_reported_no_contact),
        },
    }


# ── 批量结算 ──


def _settlement_costs(
    receipts: list[dict], *, run_id: str
) -> tuple[int, int]:
    """结算调用数与回合数：既有回执数 +1；回合按 run 去重（未知 run 如实为 0 起）."""
    calls = len(receipts) + 1
    runs = {str(e.get("run_id") or "") for e in receipts if str(e.get("run_id") or "")}
    this_run = str(run_id or "").strip()
    if this_run:
        runs.add(this_run)
    return calls, len(runs)


def _submit_rule_item(
    item: SettlementItem,
    *,
    event_store: Any,
    session_id: str,
    work_unit_id: str,
    run_id: str,
    attribution: str,
) -> dict:
    """规则侧回执写 canonical EventStore（按 submission_hash 先查后写）."""
    submission_hash = derive_submission_hash(
        decision=item.decision, benefit=item.benefit, evidence_level=item.evidence_level,
        evidence_refs=list(item.evidence_refs), note=item.note, suggestion=item.suggestion,
    )
    slot_id = derive_slot_id(
        work_unit_id=work_unit_id or session_id or "unresolved",
        kind="rule", ref=item.ref, version=item.read_version,
    )
    existing = collect_rule_feedback_receipts(event_store, session_id)
    chain = [e for e in existing if e.get("slot_id") == slot_id]
    for row in existing:
        if row.get("submission_hash") == submission_hash and row.get("slot_id") == slot_id:
            return {
                "kind": "rule", "ref": item.ref, "status": "committed",
                "idempotent": True, "slot_id": slot_id,
                "submission_hash": submission_hash,
                "revision": int(row.get("revision", 1) or 1),
                "ledger_watermark": int(row.get("seq", 0) or 0),
            }
    revision = max((int(e.get("revision", 0) or 0) for e in chain), default=0) + 1
    superseded = {str(e.get("supersedes") or "") for e in chain}
    parent = next(
        (e for e in chain if str(e.get("submission_hash") or "") not in superseded),
        None,
    )
    payload = {
        "schema": RULE_FEEDBACK_SCHEMA,
        "kind": "rule",
        "ref": item.ref,
        "read_version": item.read_version,
        "decision": item.decision,
        "benefit": item.benefit,
        "evidence_level": item.evidence_level,
        "evidence_refs": list(item.evidence_refs),
        "note": str(item.note or "")[:2000],
        "suggestion": str(item.suggestion or "")[:2000],
        "session_id": str(session_id or ""),
        "work_unit_id": str(work_unit_id or ""),
        "run_id": str(run_id or ""),
        "slot_id": slot_id,
        "submission_hash": submission_hash,
        "revision": revision,
        "supersedes": str(parent.get("submission_hash") or "") if parent else "",
        "attribution": attribution,
        "self_reported": bool(item.self_reported),
        "semantics": "model_declared_rule_execution_feedback",
    }
    if item.self_reported:
        payload["self_reported"] = True
    try:
        event = event_store.append(session_id, RULE_FEEDBACK_EVENT_TYPE, payload)
    except Exception as exc:  # noqa: BLE001 — EventStore.append 自身 fail-open 返回 None
        return {
            "kind": "rule", "ref": item.ref, "status": "failed",
            "reason": f"rule feedback event append failed: {exc}",
            "slot_id": slot_id, "submission_hash": submission_hash, "revision": revision,
        }
    if event is None:
        return {
            "kind": "rule", "ref": item.ref, "status": "failed",
            "reason": "rule feedback event store unavailable (append returned None)",
            "slot_id": slot_id, "submission_hash": submission_hash, "revision": revision,
        }
    return {
        "kind": "rule", "ref": item.ref, "status": "committed",
        "slot_id": slot_id, "submission_hash": submission_hash,
        "revision": revision, "ledger_watermark": int(getattr(event, "seq", 0) or 0),
    }


def submit_settlement_batch(
    *,
    items: Iterable[SettlementItem],
    method_store: Any = None,
    experience_store: Any = None,
    event_store: Any = None,
    session_id: str,
    work_unit_id: str = "",
    run_id: str = "",
    episode_ref: str = "",
    model: str = "",
    attribution: str = "",
    rule_lookup: Callable[[str], bool] | None = None,
) -> dict:
    """批量结算：逐条校验、逐条持久化、逐条回执（committed/pending/failed）.

    批量部分成功不宣称整批原子完成；写入未知（durability uncertain）返回
    pending 并附 submission_hash 查询提示，不谎报成功、不盲目重发。
    """
    wu = str(work_unit_id or "").strip()
    label = attribution.strip() if attribution.strip() else (f"task({wu})" if wu else "unresolved")
    entry_attribution = label if wu else "unresolved"
    existing_receipts = _receipts_for_session(method_store, experience_store, event_store, session_id)
    wu_receipts = [e for e in existing_receipts if _receipt_work_unit(e) == wu] if wu else existing_receipts
    settlement_calls, settlement_rounds = _settlement_costs(wu_receipts, run_id=run_id)

    receipts: list[dict] = []
    counts = {"committed": 0, "pending": 0, "failed": 0}
    for item in items:
        receipts.append(
            _submit_one(
                item,
                method_store=method_store,
                experience_store=experience_store,
                event_store=event_store,
                session_id=session_id,
                work_unit_id=wu,
                run_id=run_id,
                episode_ref=episode_ref,
                model=model,
                entry_attribution=entry_attribution,
                rule_lookup=rule_lookup,
            )
        )
    for receipt in receipts:
        counts[receipt["status"]] += 1

    return {
        "work_unit_id": wu,
        "attribution": f"task({wu})" if wu else "degraded(session)",
        "settlement_calls": settlement_calls,
        "settlement_rounds": settlement_rounds,
        "counts": counts,
        "receipts": receipts,
        "coverage_boundary": COVERAGE_BOUNDARY,
    }


def _submit_one(
    item: SettlementItem,
    *,
    method_store: Any,
    experience_store: Any,
    event_store: Any,
    session_id: str,
    work_unit_id: str,
    run_id: str,
    episode_ref: str,
    model: str,
    entry_attribution: str,
    rule_lookup: Callable[[str], bool] | None,
) -> dict:
    kind = str(item.kind or "").strip()
    ref = str(item.ref or "").strip()
    decision = str(item.decision or "").strip()
    benefit = str(item.benefit or "unknown").strip()
    evidence_level = str(item.evidence_level or "model_declared").strip()

    def failed(reason: str) -> dict:
        return {"kind": kind, "ref": ref, "status": "failed", "reason": reason}

    def pending(submission_hash: str, detail: str) -> dict:
        return {
            "kind": kind, "ref": ref, "status": "pending",
            "reason": detail,
            "hint": (
                f"写入结果未知：先按 submission_hash={submission_hash} 查原结算，"
                "命中且全字段一致视为已提交；未命中才允许同内容重发（键去重使重发安全）"
            ),
        }

    if kind not in _KNOWN_KINDS:
        return failed(f"unknown kind: {kind}")
    if not ref:
        return failed("missing ref")
    if decision not in _DECISIONS:
        return failed(f"decision must be one of {sorted(_DECISIONS)}")
    if benefit not in _BENEFITS:
        return failed(f"benefit must be one of {sorted(_BENEFITS)}")
    if evidence_level not in _LEVELS:
        return failed(f"evidence_level must be one of {sorted(_LEVELS)}")

    submission_hash = derive_submission_hash(
        decision=decision, benefit=benefit, evidence_level=evidence_level,
        evidence_refs=list(item.evidence_refs), note=item.note, suggestion=item.suggestion,
    )

    if kind == "rule":
        if rule_lookup is not None:
            try:
                exists = bool(rule_lookup(ref))
            except Exception:  # noqa: BLE001
                exists = False
            if not exists:
                return failed(f"rule ref not found via rule_lookup: {ref}")
        elif not _RULE_REF_RE.fullmatch(ref):
            return failed(f"rule ref malformed and no rule_lookup provided: {ref}")
        receipt = _submit_rule_item(
            item,
            event_store=event_store,
            session_id=session_id,
            work_unit_id=work_unit_id,
            run_id=run_id,
            attribution=entry_attribution,
        )
        if item.self_reported and receipt.get("status") == "committed":
            receipt["self_reported"] = True
        return receipt

    store = method_store if kind == "method" else experience_store
    if store is None:
        return failed(f"{kind} store not assembled")

    if item.self_reported:
        try:
            exists = store.get(ref) is not None
        except Exception:  # noqa: BLE001
            exists = False
        if not exists:
            return failed(f"self_reported ref not found: {ref}")

    common = dict(
        note=item.note,
        model=model,
        evidence_refs=list(item.evidence_refs),
        session_id=session_id,
        work_unit_id=work_unit_id,
        benefit=benefit,
        evidence_level=evidence_level,
        suggestion=item.suggestion,
        supersedes=item.supersedes,
        read_version=item.read_version,
        run_id=run_id,
        attribution=entry_attribution,
        self_reported=item.self_reported,
    )
    try:
        if kind == "method":
            # P1-1：不伪造 episode 哨兵——wu/episode 皆空时显式走 store 的
            # unresolved 退化路径（binding=unresolved、slot_id=''，use_ledger
            # 已定义），不同无归属任务不并入同一伪 slot 修订链。
            entry = store.record_use(
                ref,
                episode_ref=episode_ref,
                decision=decision,
                allow_unresolved=True,
                **common,
            )
        else:
            # P1-2：experience 侧补传 episode_ref，与 method 侧层级一致
            # （显式工作单元 > episode 回退 > unresolved）。
            entry = store.record_use(
                ref.removeprefix("experience:"),
                use_decision=decision,
                episode_ref=episode_ref,
                **common,
            )
    except FileNotFoundError:
        return failed(f"ref not found: {ref}")
    except (ValueError, PermissionError) as exc:
        return failed(f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 — uncertain/durable 一律 pending，不谎报
        name = type(exc).__name__
        if "Uncertain" in name:
            return pending(submission_hash, f"{name}: {exc}")
        return failed(f"{name}: {exc}")

    receipt = {
        "kind": kind,
        "ref": ref,
        "status": "committed",
        "idempotent": bool(entry.get("idempotent")),
        "slot_id": str(entry.get("slot_id") or ""),
        "submission_hash": str(entry.get("submission_hash") or ""),
        "revision": int(entry.get("revision", 1) or 1),
        "ledger_watermark": int(entry.get("ledger_watermark", 0) or 0),
    }
    if item.self_reported:
        receipt["self_reported"] = True
    return receipt


# ── 规则反馈投影（P1 注释通道数据源）──


def _scan_event_files(root: Path) -> Iterable[dict]:
    """扫描 event_logs_dir 的单文件与多段布局，产出机械事件 dict（fail-open）."""
    if not root.is_dir():
        return
    for path in sorted(root.glob("*.jsonl")):
        yield from _parse_event_file(path)
    for seg_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(seg_dir.glob("*.jsonl")):
            yield from _parse_event_file(path)


def _parse_event_file(path: Path) -> Iterable[dict]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


class _ProjectionCache(TypedDict):
    """RuleFeedbackProjection 的 TTL 缓存载荷（三视图一次性物化）.

    修正原 ``dict[str, dict]`` 注解：receipt_pairs 实为 set、reads 实为
    list[str] 聚合，按真实键型精确建模（仅类型层，无运行时影响）。
    """

    feedback: dict[str, dict]
    reads: dict[str, list[str]]
    receipt_pairs: set[tuple[str, str]]


class RuleFeedbackProjection:
    """规则反馈注释通道的数据投影：EventStore → per-rule 聚合（可重建，非真相源）.

    只读派生视图：执行回执次数、最近问题一句话摘要、pending_count 与反馈
    水位。不改规则排序、不改规则权威（有效性来自已批准的权威来源）。
    带短 TTL 缓存避免高频检索重复全量扫描。
    """

    def __init__(self, event_logs_dir: str | Path, *, ttl_seconds: float = 10.0) -> None:
        self._dir = Path(event_logs_dir)
        self._ttl = float(ttl_seconds)
        self._cached_at = 0.0
        # 缓存槽位默认 None（falsy）：与原空 dict 同样令 TTL 判定走重扫路径，
        # 首次 _aggregate 前不返回任何投影；键型见 _ProjectionCache。
        self._cache: _ProjectionCache | None = None

    def _aggregate(self) -> _ProjectionCache:
        now = time.monotonic()
        if now - self._cached_at < self._ttl and self._cache:
            return self._cache
        feedback: dict[str, list[dict]] = {}
        reads: dict[str, list[str]] = {}
        receipt_pairs: set[tuple[str, str]] = set()
        watermark: dict[str, str] = {}
        for row in _scan_event_files(self._dir):
            event_type = str(row.get("type") or "")
            # 先落名再 isinstance：调用表达式不可收窄，直接内联会让 payload
            # 残留 None 分支；经局部名收窄后恒为 mapping（else 分支 {}）。
            raw_payload = row.get("payload")
            payload = raw_payload if isinstance(raw_payload, dict) else {}
            ref = str(payload.get("ref") or row.get("ref") or "")
            if not ref:
                continue
            ts = str(row.get("ts") or "")
            if event_type == RULE_FEEDBACK_EVENT_TYPE:
                feedback.setdefault(ref, []).append({**payload, "ts": ts})
                # 版本级抵扣口径：回执携带 read_version 才能抵扣同版本读取；
                # 无版本回执只计入 count，不做版本级抵扣（与工具迹降级同口径）。
                receipt_pairs.add((ref, str(payload.get("read_version") or "")))
                if ts > watermark.get(ref, ""):
                    watermark[ref] = ts
            elif event_type == KNOWLEDGE_READ_EVENT_TYPE:
                reads.setdefault(ref, []).append(str(payload.get("version") or ""))
        aggregated: dict[str, dict] = {}
        for ref, entries in feedback.items():
            deduped: dict[str, dict] = {}
            for entry in entries:
                key = str(entry.get("submission_hash") or "")
                deduped.setdefault(key or f"ts:{entry.get('ts')}", entry)
            unique = sorted(deduped.values(), key=lambda e: str(e.get("ts") or ""))
            recent_issue = ""
            for entry in reversed(unique):
                if str(entry.get("benefit") or "") in {"hindered", "mixed"} or str(
                    entry.get("decision") or ""
                ) == "rejected":
                    recent_issue = " ".join(str(entry.get("note") or "").split())[:160]
                    break
            aggregated[ref] = {
                "count": len(unique),
                "recent_issue": recent_issue,
                "watermark": watermark.get(ref, ""),
            }
        self._cache = {
            "feedback": aggregated,
            "reads": reads,
            "receipt_pairs": receipt_pairs,
        }
        self._cached_at = now
        return self._cache

    def __call__(self, rule_ref: str) -> dict | None:
        ref = str(rule_ref or "").strip().upper()
        if not ref:
            return None
        try:
            data = self._aggregate()
        except Exception:  # noqa: BLE001 — 注释通道 fail-open
            return None
        feedback = data["feedback"].get(ref)
        read_versions = list(data["reads"].get(ref, []))
        if feedback is None and not read_versions:
            return None  # 无反馈无读取：不附加任何字段
        count = int(feedback["count"]) if feedback else 0
        pending = sum(
            1 for version in read_versions if (ref, version) not in data["receipt_pairs"]
        )
        projection: dict[str, Any] = {
            "rule_feedback_count": count,
            "rule_recent_issue": str(feedback["recent_issue"]) if feedback else "",
            "rule_pending_count": pending,
            "rule_feedback_watermark": str(feedback["watermark"]) if feedback else "",
            "rule_feedback_source": "eventstore_projection",
        }
        return projection
