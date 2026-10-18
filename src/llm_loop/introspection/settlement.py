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

import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from llm_loop.introspection.event_scan_cache import scan_event_files
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


def _normalize_rule_ref(ref: str) -> str:
    """规则 ref 归一：RULE-AI-N 模式统一大写（P-SET-5）.

    提交（slot/载荷/回执）、投影摄取与查询侧三处同一口径——大小写不同的
    同一规则不再产生不同 slot 或互相漏读；非规则模式的 ref 原样保留
    （method/experience ref 大小写敏感，不在此归一）。
    """
    cleaned = str(ref or "").strip()
    return cleaned.upper() if _RULE_REF_RE.fullmatch(cleaned) else cleaned


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


@dataclass(frozen=True)
class SettlementChannel:
    """受限结算通道的工厂装配件（模型工具面 ← 结算核心的绑定视图）.

    由 factory 在 EventStore 启用时构造并注入 ``CorrectionContext.settlement``；
    未装配（None）时 ``settlement_pending`` / ``settlement_submit`` 回执
    "通道不可用"（零行为：不伪造清单、不落任何账）。本类只持绑定引用，
    不含新行为——校验/持久化/回执三分全部由上述结算函数承担。
    ``event_logs_dir``（P-SET-7）：EventStore 同源事件目录——确定任务 slot
    的规则回执跨会话查重/抵扣经该目录投影扫描；None 时退回会话内口径。
    """

    event_store: Any
    method_store: Any | None = None
    experience_store: Any | None = None
    rule_lookup: Callable[[str], bool] | None = None
    event_logs_dir: str | Path | None = None


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


def _ledger_receipts(
    store: Any, *, session_id: str = "", work_unit_id: str = ""
) -> tuple[list[dict], int]:
    """读取一侧 usage ledger 的 v2 结算回执并按窗口过滤（fail-open）.

    P-SET-3：experience 侧 ``usage_entries`` 默认 ``limit=200`` 截断会让较旧
    回执滑出窗口后重现待结算清单（诱导重报）；此处显式请求无界读取
    （store 支持 ``limit=None``），与 method 侧无界口径对齐。假 store 兼容
    旧签名（TypeError 逐级回退到无参/单参调用）。
    P-SET-2：降级 session 窗口下，session_id 为空的回执无法证明归属本会话
    ——不参与抵扣；排除的 legacy 行数如实返回（清单 window 显式披露），
    不静默抵扣。确定任务窗口按工作单元匹配，不看 session。

    返回 ``(窗口内回执列表, 被排除的空 session legacy 行数)``。
    """
    if store is None:
        return [], 0
    entries: list | None = None
    for kwargs in ({"limit": None}, {}):
        try:
            entries = list(store.usage_entries(**kwargs) or [])
            break
        except TypeError:
            continue
        except Exception:  # noqa: BLE001 — fail-open
            return [], 0
    if entries is None:
        try:
            entries = list(store.usage_entries("") or [])
        except Exception:  # noqa: BLE001 — fail-open
            return [], 0
    wu = str(work_unit_id or "").strip()
    sid = str(session_id or "")
    out: list[dict] = []
    legacy_excluded = 0
    for entry in entries:
        if not (isinstance(entry, dict) and entry.get("submission_hash")):
            continue
        if wu:
            if _receipt_work_unit(entry) == wu:
                out.append(entry)
            continue
        entry_sid = str(entry.get("session_id") or "")
        if entry_sid:
            if entry_sid == sid:
                out.append(entry)
        else:
            # 空 session 回执：不抵扣降级窗口（P-SET-2）
            legacy_excluded += 1
    return out, legacy_excluded


def _receipt_ref(entry: dict) -> str:
    return str(entry.get("method_ref") or entry.get("experience_ref") or entry.get("ref") or "")


def _receipt_version(entry: dict) -> str:
    return str(entry.get("read_version") or "")


def _receipt_work_unit(entry: dict) -> str:
    return str(entry.get("work_unit_id") or "")


def _scan_rule_feedback_rows(root: Path, *, work_unit_id: str) -> list[dict]:
    """跨会话扫描 event_logs_dir 中匹配工作单元的 rule.feedback 回执（fail-open）.

    P-SET-7：确定任务 slot 的规则回执身份是工作单元×对象×版本——与落在哪个
    会话文件无关。此处按 ``work_unit_id`` 过滤投影扫描（复用 RuleFeedback
    Projection 的文件布局遍历），返回与 ``collect_rule_feedback_receipts``
    同构的合并行（payload 键 + type/ts/seq，附行级 session_id）。
    """
    wu = str(work_unit_id or "").strip()
    if not wu or not root.is_dir():
        return []
    rows: list[dict] = []
    scan_rows, _wm = scan_event_files(root, keep_types=(RULE_FEEDBACK_EVENT_TYPE,))
    for row in scan_rows:
        raw_payload = row.get("payload")
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        if str(payload.get("work_unit_id") or "") != wu:
            continue
        try:
            merged = {
                **payload,
                "type": RULE_FEEDBACK_EVENT_TYPE,
                "ts": str(row.get("ts") or ""),
                "seq": int(row.get("seq") or 0),
                "session_id": str(row.get("session_id") or payload.get("session_id") or ""),
            }
        except (TypeError, ValueError):  # noqa: BLE001 — 单行畸形不阻断扫描
            continue
        rows.append(merged)
    return rows


def _rule_receipts(
    event_store: Any,
    session_id: str,
    *,
    work_unit_id: str = "",
    event_logs_dir: str | Path | None = None,
) -> list[dict]:
    """规则侧回执：本会话事件 +（确定任务时）跨会话投影扫描（fail-open）.

    P-SET-7：确定任务窗口下，同工作单元任意会话的 rule.feedback 回执进入
    匹配集（与 ledger 侧同工作单元口径对齐）；降级窗口 slot 以会话为身份，
    不做跨会话扫描。当前会话行已含于 ``collect_rule_feedback_receipts``
    （event_store 与 event_logs_dir 同源时按行级 session 去重，不重复计入）。
    """
    rows = collect_rule_feedback_receipts(event_store, session_id)
    wu = str(work_unit_id or "").strip()
    if not wu or not event_logs_dir:
        return rows
    try:
        cross = _scan_rule_feedback_rows(Path(event_logs_dir), work_unit_id=wu)
    except Exception:  # noqa: BLE001 — fail-open：投影扫描失败退回会话内口径
        return rows
    sid = str(session_id or "")
    rows.extend(r for r in cross if str(r.get("session_id") or "") != sid)
    return rows


def _receipts_for_session(
    method_store: Any,
    experience_store: Any,
    event_store: Any,
    session_id: str,
    *,
    work_unit_id: str = "",
    event_logs_dir: str | Path | None = None,
) -> tuple[list[dict], int]:
    """窗口内回执集合：两侧 ledger（无界+窗口过滤）+ 规则事件.

    返回 ``(回执列表, 被排除的空 session legacy ledger 行数)``——后者供
    清单 window 披露（P-SET-2 显式标注，不静默吞行）。
    """
    receipts: list[dict] = []
    legacy_excluded = 0
    for store in (method_store, experience_store):
        rows, n_legacy = _ledger_receipts(
            store, session_id=session_id, work_unit_id=work_unit_id
        )
        receipts.extend(rows)
        legacy_excluded += n_legacy
    receipts += _rule_receipts(
        event_store, session_id, work_unit_id=work_unit_id, event_logs_dir=event_logs_dir
    )
    return receipts, legacy_excluded


def _offsets(read: dict, receipts: list[dict], *, work_unit_id: str, session_id: str) -> bool:
    """回执是否抵扣该读取事实：工作单元×对象×读取版本三元组匹配.

    确定任务窗口：跳过 attribution=unresolved 的回执（降级窗口回执不抵扣
    确定任务，也不进任务级覆盖率分母）。
    降级 session 窗口（P-SET-2）：只接受「回执自身携带非空且等于本会话的
    session_id」的回执——空 session 回执（legacy 行）无法证明归属本会话，
    不参与抵扣（排除数经清单 window.legacy_receipts_without_session_excluded
    披露，不静默抵扣）。
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
            entry_sid = str(entry.get("session_id") or "")
            if not entry_sid or entry_sid != session_id:
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
    event_logs_dir: str | Path | None = None,
) -> dict:
    """待结算清单 = 读取事件 − 持久化结算回执（fail-open 投影，非新账本）."""
    wu = str(work_unit_id or "").strip()
    reads = collect_knowledge_reads(event_store, session_id)
    read_source = "knowledge_read_events"
    items: list[dict] = []
    legacy_excluded = 0
    # P1-3：读取事件先按唯一键 (kind, ref, version) 收敛——settled_count 的单位是
    # "被回执抵扣的唯一键数"，同 key 重复读取不得虚增已结算数。
    read_keys: set[tuple[str, str, str]] = {
        (str(r.get("kind") or ""), str(r.get("ref") or ""), str(r.get("version") or ""))
        for r in reads
    }

    if reads:
        receipts, legacy_excluded = _receipts_for_session(
            method_store,
            experience_store,
            event_store,
            session_id,
            work_unit_id=wu,
            event_logs_dir=event_logs_dir,
        )
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
            # P-SET-2：降级窗口排除的空 session legacy ledger 行数（显式标注，
            # 不静默抵扣也不静默吞行）；确定任务窗口按工作单元匹配，恒为 0。
            "legacy_receipts_without_session_excluded": legacy_excluded,
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
    event_logs_dir: str | Path | None = None,
) -> dict:
    """规则侧回执写 canonical EventStore（按 (slot, submission_hash) 先查后写）.

    P-SET-5：ref 归一后入 slot/载荷/回执；supersedes 显式支持——请求父必须
    是同 slot 链上既有 submission_hash，校验失败回 failed 并给原因（不静默
    忽略，也不产生断链/环）；未显式请求时沿用程序推导的链头为父。
    P-SET-7：确定任务 slot（work_unit_id 非空）查重跨会话——同
    (slot, submission_hash) 跨会话重提返回幂等回执，不追加重复事件；
    降级 slot 以会话为身份，维持会话内查重（跨会话本就是不同 slot）。
    """
    ref = _normalize_rule_ref(item.ref)
    submission_hash = derive_submission_hash(
        decision=item.decision, benefit=item.benefit, evidence_level=item.evidence_level,
        evidence_refs=list(item.evidence_refs), note=item.note, suggestion=item.suggestion,
    )
    slot_id = derive_slot_id(
        work_unit_id=work_unit_id or session_id or "unresolved",
        kind="rule", ref=ref, version=item.read_version,
    )
    existing = collect_rule_feedback_receipts(event_store, session_id)
    if work_unit_id and event_logs_dir:
        try:
            cross = _scan_rule_feedback_rows(Path(event_logs_dir), work_unit_id=work_unit_id)
        except Exception:  # noqa: BLE001 — fail-open：跨会话扫描失败退回会话内查重
            cross = []
        sid = str(session_id or "")
        existing.extend(r for r in cross if str(r.get("session_id") or "") != sid)
    chain = [e for e in existing if e.get("slot_id") == slot_id]
    for row in existing:
        if row.get("submission_hash") == submission_hash and row.get("slot_id") == slot_id:
            return {
                "kind": "rule", "ref": ref, "status": "committed",
                "idempotent": True, "slot_id": slot_id,
                "submission_hash": submission_hash,
                "revision": int(row.get("revision", 1) or 1),
                "ledger_watermark": int(row.get("seq", 0) or 0),
            }
    revision = max((int(e.get("revision", 0) or 0) for e in chain), default=0) + 1
    requested = str(item.supersedes or "").strip()
    parent = None
    if requested:
        # 显式 supersedes：父必须存在于同 slot 链（P-SET-5，与 ledger 侧
        # resolve_submission 的父校验同口径）；不满足如实 failed。
        parent = next(
            (e for e in chain if str(e.get("submission_hash") or "") == requested), None,
        )
        if parent is None:
            return {
                "kind": "rule", "ref": ref, "status": "failed",
                "reason": (
                    "supersedes parent not found in rule slot chain "
                    "(must be an existing submission_hash of the same slot)"
                ),
                "slot_id": slot_id, "submission_hash": submission_hash,
            }
    else:
        superseded = {str(e.get("supersedes") or "") for e in chain}
        parent = next(
            (e for e in chain if str(e.get("submission_hash") or "") not in superseded),
            None,
        )
    payload = {
        "schema": RULE_FEEDBACK_SCHEMA,
        "kind": "rule",
        "ref": ref,
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
        "supersedes": requested or (str(parent.get("submission_hash") or "") if parent else ""),
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
            "kind": "rule", "ref": ref, "status": "failed",
            "reason": f"rule feedback event append failed: {exc}",
            "slot_id": slot_id, "submission_hash": submission_hash, "revision": revision,
        }
    if event is None:
        return {
            "kind": "rule", "ref": ref, "status": "failed",
            "reason": "rule feedback event store unavailable (append returned None)",
            "slot_id": slot_id, "submission_hash": submission_hash, "revision": revision,
        }
    return {
        "kind": "rule", "ref": ref, "status": "committed",
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
    event_logs_dir: str | Path | None = None,
) -> dict:
    """批量结算：逐条校验、逐条持久化、逐条回执（committed/pending/failed）.

    批量部分成功不宣称整批原子完成；写入未知（durability uncertain）返回
    pending 并附 submission_hash 查询提示，不谎报成功、不盲目重发。
    ``event_logs_dir``（P-SET-7）：确定任务 slot 的规则回执查重跨会话——
    经投影扫描同工作单元的全部 rule.feedback 事件，不追加重复事件。
    """
    wu = str(work_unit_id or "").strip()
    label = attribution.strip() if attribution.strip() else (f"task({wu})" if wu else "unresolved")
    entry_attribution = label if wu else "unresolved"
    existing_receipts, _legacy_excluded = _receipts_for_session(
        method_store,
        experience_store,
        event_store,
        session_id,
        work_unit_id=wu,
        event_logs_dir=event_logs_dir,
    )
    if wu:
        window_receipts = [e for e in existing_receipts if _receipt_work_unit(e) == wu]
    else:
        # P-SET-6：降级窗口成本口径与 _offsets 对齐——只计本会话回执；
        # 两侧全局账本里其他会话/其他工作单元的回执不再虚增本窗口的
        # settlement_calls/settlement_rounds（B1 回执探针 A6：本会话首笔
        # 提交回 calls=5 即此口径混入所致）。
        sid = str(session_id or "")
        window_receipts = [
            e for e in existing_receipts if str(e.get("session_id") or "") == sid
        ]
    settlement_calls, settlement_rounds = _settlement_costs(window_receipts, run_id=run_id)

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
                event_logs_dir=event_logs_dir,
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
    event_logs_dir: str | Path | None = None,
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
        # P-SET-5：RULE-AI-N 模式 ref 提交时归一为大写——slot/载荷/回执与
        # 投影查询同一口径（rule_exists 查询侧本就 upper()，此处补齐提交侧）。
        ref = _normalize_rule_ref(ref)
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
            event_logs_dir=event_logs_dir,
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


class _ProjectionCache(TypedDict):
    """RuleFeedbackProjection 的 TTL 缓存载荷（三视图一次性物化 + 覆盖水位）.

    修正原 ``dict[str, dict]`` 注解：receipt_pairs 实为 set、reads 实为
    list[str] 聚合，按真实键型精确建模（仅类型层，无运行时影响）。
    indexed_watermark 是投影本次扫描已覆盖到的最新事件 ts——TTL 缓存命中的
    旧快照据此披露旧水位，而不是旧数据冒充新（设计草案 v3 :106/:163）。
    """

    feedback: dict[str, dict]
    reads: dict[str, list[str]]
    receipt_pairs: set[tuple[str, str]]
    indexed_watermark: str


class RuleFeedbackProjection:
    """规则反馈注释通道的数据投影：EventStore → per-rule 聚合（可重建，非真相源）.

    只读派生视图：执行回执次数、最近问题一句话摘要、pending_count 与反馈
    水位。不改规则排序、不改规则权威（有效性来自已批准的权威来源）。
    带短 TTL 缓存避免高频检索重复全量扫描；投影自带 indexed_watermark
    （覆盖边界），TTL 命中的旧快照以旧水位如实披露，不冒充已含新事件
    （设计草案 v3 决策表：投影落后 → 显示落后水位而非旧数据冒充新）。
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
        # TASK-fdc7603b-001 C 线：投影覆盖边界水位——本次扫描已见到的最新事件
        # ts（含无 ref 事件）。TTL 命中的旧快照以旧 indexed_watermark 披露。
        scan_rows, indexed_watermark = scan_event_files(
            self._dir, keep_types=(RULE_FEEDBACK_EVENT_TYPE, KNOWLEDGE_READ_EVENT_TYPE)
        )
        for row in scan_rows:
            event_type = str(row.get("type") or "")
            # 先落名再 isinstance：调用表达式不可收窄，直接内联会让 payload
            # 残留 None 分支；经局部名收窄后恒为 mapping（else 分支 {}）。
            raw_payload = row.get("payload")
            payload = raw_payload if isinstance(raw_payload, dict) else {}
            ts = str(row.get("ts") or "")
            ref = str(payload.get("ref") or row.get("ref") or "").strip()
            # P-SET-5：规则 ref 入投影前归一（RULE-AI-N 模式统一大写）——
            # 与查询侧 upper() 对称，legacy 小写载荷行同样收敛到同一键；
            # 非规则模式 ref（method/experience）大小写敏感，不在此归一。
            if _RULE_REF_RE.fullmatch(ref):
                ref = ref.upper()
            if not ref:
                continue
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
            deduped: dict[tuple[str, str], dict] = {}
            for entry in entries:
                hash_key = str(entry.get("submission_hash") or "")
                # P-SET-1：去重键补 slot_id——同内容跨 slot（不同工作单元对
                # 同一规则）不是重试，不折叠（两层身份原则）；同 slot 同
                # hash（传输层重试/重复事件）仍收敛为一条。无 hash 的
                # legacy 行退化为 ts 键，防止不同事件误并。
                key = (str(entry.get("slot_id") or ""), hash_key or f"ts:{entry.get('ts')}")
                deduped.setdefault(key, entry)
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
            "indexed_watermark": indexed_watermark,
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
            "rule_feedback_indexed_watermark": str(data["indexed_watermark"]),
            "rule_feedback_source": "eventstore_projection",
        }
        return projection
