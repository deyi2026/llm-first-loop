"""TASK-ac085ab1-001 P0 记录契约: 两侧 usage ledger 共用的两层幂等键与行级完整性凭据.

设计来源: docs/LFL 任务知识使用反馈与检索闭环设计草案.md v3
（「幂等键与重复结算」「边界与失败模式决策表」）：

- slot_id = sha256(工作单元id, kind, 稳定ref, 读取版本标识) —— 评价归属槽位；
  回答"哪个工作单元对哪个对象的哪个版本作出过评价"。
- submission_hash = sha256(提交内容字段的规范序列化: 使用决定、本次帮助、
  评价依据、证据引用、建议) —— 提交内容身份；"相同提交"由此获得机械定义。
  两层键均由程序派生，模型不自选；ts 不参与键、也不作为排序权威。
- 落账先扫后写（复用 record_migrated_entry 的 dedupe_key 先例，扩展到两侧
  live record_use 路径）：flock 单写锁内 (对象ref, slot, submission_hash)
  已存在则返回既有条目，传输层重试与重复提交折叠为一条；同内容跨对象、
  跨 slot（不同工作单元 / 已归属 vs 未归属）不是重试，不折叠——旧反馈
  不串任务，每项可查持久 receipt。
- 同 slot 不同提交是修订：追加新条目并经 supersedes 链回原条目，不改写历史行；
  落账前程序校验父记录（存在、同 slot、在链上），失败如实拒绝。
- 行级完整性凭据: 规范序列化字节的 sha256 写入行内 ``integrity`` 字段。
  恢复扫描只越过校验通过的记录；校验失败的尾部移入隔离旁文件并出具诊断报告
  （位置、字节范围、疑似原因），不静默跳过、不直接在坏行上追加
  （EVO-20261010 账本损失教训：行数水位的半行盲区）。

本模块只提供机械派生与账本读写原语；语义判断归模型，净分统计裁决归
usage_net.py（legacy 桶按字段齐全度参与的分层口径见各 store.usage_net）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

SCHEMA_METHOD_V2 = "method-use/v2"
SCHEMA_EXPERIENCE_V2 = "experience-use/v2"

DECISIONS = frozenset({"applied", "adapted", "not_applicable", "rejected"})
BENEFITS = frozenset({"helped", "neutral", "hindered", "unknown", "mixed"})
EVIDENCE_LEVELS = frozenset(
    {"model_declared", "observation_linked", "independently_evaluated"}
)

_QUARANTINE_SUFFIX = ".corrupt"
_QUARANTINE_REPORT_SUFFIX = ".corrupt.report.json"


def canonical_json(payload: dict) -> str:
    """规范序列化：排序键、紧凑分隔、非 ASCII 原样（字节级稳定）。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def derive_slot_id(*, work_unit_id: str, kind: str, ref: str, version: str) -> str:
    """slot 身份：工作单元 × 对象 × 读取版本（程序派生，不含 ts）。"""
    material = canonical_json(
        {
            "work_unit_id": str(work_unit_id or ""),
            "kind": str(kind or ""),
            "ref": str(ref or ""),
            "version": str(version or ""),
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def derive_submission_hash(
    *,
    decision: str,
    benefit: str,
    evidence_level: str,
    evidence_refs: list[str],
    note: str,
    suggestion: str,
) -> str:
    """提交内容身份：决定/自评/依据/证据/建议五要素的规范序列化哈希。"""
    material = canonical_json(
        {
            "decision": str(decision or ""),
            "benefit": str(benefit or ""),
            "evidence_level": str(evidence_level or ""),
            "evidence_refs": [str(v) for v in (evidence_refs or [])],
            "note": str(note or ""),
            "suggestion": str(suggestion or ""),
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def with_line_integrity(entry: dict) -> dict:
    """返回带行级完整性凭据的副本（凭据 = 除 integrity 外全字段的规范序列化哈希）。"""
    payload = {k: v for k, v in entry.items() if k != "integrity"}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return {**payload, "integrity": digest}


def line_integrity_matches(entry: dict) -> bool:
    """按行内 integrity 凭据复核该行未被写后改写。"""
    recorded = str(entry.get("integrity") or "")
    if not recorded:
        return True  # legacy 行无凭据：可解析即视为完好（分层统计另行标注）
    payload = {k: v for k, v in entry.items() if k != "integrity"}
    expected = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return recorded == expected


@dataclass(frozen=True)
class LedgerDecision:
    """先扫后写在锁内得出的落账决定（dedupe / append / invalid）。"""

    action: str
    existing: dict | None = None
    parent: dict | None = None
    revision: int = 1
    reason: str = ""


def _chain_sort_key(row: dict) -> tuple[int, int]:
    """链内排序键：(revision, ledger_seq)——追加序权威，ts 不参与。"""
    try:
        seq = int(row.get("ledger_seq", 0) or 0)
    except (TypeError, ValueError):
        seq = 0
    try:
        rev = int(row.get("revision", 0) or 0)
    except (TypeError, ValueError):
        rev = 0
    return (rev, seq)


def _chain_parent(chain: list[dict]) -> dict | None:
    """链头 = 链内未被任何同 slot 条目 supersedes 引用的最新一条（顺序无关）."""
    if not chain:
        return None
    superseded = {
        str(row.get("supersedes") or "") for row in chain if row.get("supersedes")
    }
    heads = [row for row in chain if str(row.get("submission_hash") or "") not in superseded]
    return sorted(heads or chain, key=_chain_sort_key)[-1]


def resolve_submission(
    existing_entries: list[dict],
    *,
    slot_id: str,
    submission_hash: str,
    object_field: str,
    object_ref: str,
    requested_supersedes: str = "",
) -> LedgerDecision:
    """锁内先扫后写：同 (对象, slot, submission_hash) 折叠为既有条目；同 slot 不同内容为修订.

    - 去重对象边界（P1 修复，Rule28 审查 20261015-ac085ab1）：submission_hash
      材料不含对象身份，全默认内容跨对象哈希恒等；匹配行必须与本次提交同对象
      （object_field 字段值 == object_ref）且 slot 空值一致——slot='' 只折叠
      slot='' 的未归属行，非空 slot 只折叠同 slot 行。缺任一边界会把第二个
      对象的回执串成第一个对象的既有行且自身永不落账（违反「旧反馈不串任务」
      「每项可查持久 receipt」），或把未归属提交折叠进已归属行。
    - 显式 supersedes 校验父记录：必须存在于账本、属同一 slot（在链上）；
      不满足返回 invalid + 原因，调用方据此给 failed 回执，不产生断链或环。
    """
    for row in existing_entries:
        if not isinstance(row, dict):
            continue
        if str(row.get("submission_hash") or "") != submission_hash:
            continue
        if str(row.get("slot_id") or "") != slot_id:
            continue  # slot 空值不一致：未归属不并已归属，跨 slot 不是重试
        if str(row.get(object_field) or "") != object_ref:
            continue  # 同默认内容跨对象（ref 不同）：哈希恒等也不是重试
        return LedgerDecision(action="dedupe", existing=row)

    if slot_id:
        chain = [
            row
            for row in existing_entries
            if isinstance(row, dict) and str(row.get("slot_id") or "") == slot_id
        ]
        if requested_supersedes:
            parent = next(
                (
                    row
                    for row in chain
                    if str(row.get("submission_hash") or "") == requested_supersedes
                ),
                None,
            )
            if parent is None:
                anywhere = any(
                    str(row.get("submission_hash") or "") == requested_supersedes
                    for row in existing_entries
                    if isinstance(row, dict)
                )
                reason = (
                    "supersedes parent belongs to another slot"
                    if anywhere
                    else "supersedes parent not found in ledger"
                )
                return LedgerDecision(action="invalid", reason=reason)
            revision = max(int(p.get("revision", 0) or 0) for p in chain) + 1
            return LedgerDecision(action="append", parent=parent, revision=revision)
        parent = _chain_parent(chain)
        revision = (
            max(int(row.get("revision", 0) or 0) for row in chain) + 1 if chain else 1
        )
        return LedgerDecision(action="append", parent=parent, revision=revision)
    return LedgerDecision(action="append", parent=None, revision=1)


def dedupe_slot_heads(entries: list[dict]) -> list[dict]:
    """统计前按 slot 取链头：同 slot 只留现行评价，修订不重复计数.

    无 slot_id 的 legacy 条目原样保留（分层口径由调用方按字段齐全度处理）。
    保持输入相对顺序。
    """
    by_slot: dict[str, list[dict]] = {}
    legacy: list[dict] = []
    ordered: list[tuple[str, dict]] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        slot = str(row.get("slot_id") or "")
        if not slot:
            legacy.append(row)
            ordered.append(("", row))
            continue
        by_slot.setdefault(slot, []).append(row)
        ordered.append((slot, row))
    head_ids: set[int] = set()
    for chain in by_slot.values():
        head = _chain_parent(chain)
        if head is not None:
            head_ids.add(id(head))
    result: list[dict] = []
    for _slot, row in ordered:
        if row in legacy or id(row) in head_ids:
            result.append(row)
    return result


@dataclass
class LineCheck:
    lineno: int
    byte_start: int
    byte_end: int
    ok: bool
    reason: str
    entry: dict | None = None
    ends_with_newline: bool = True
    suspected_cause: str = ""


def _check_line(
    raw_bytes: bytes, lineno: int, byte_start: int, ends_with_newline: bool
) -> LineCheck:
    byte_end = byte_start + len(raw_bytes)
    stripped = raw_bytes[:-1] if raw_bytes.endswith(b"\n") else raw_bytes
    if stripped.endswith(b"\r"):
        stripped = stripped[:-1]
    text = stripped.decode("utf-8", errors="replace")
    if not text.strip():
        return LineCheck(
            lineno, byte_start, byte_end, ok=True, reason="blank", entry=None,
            ends_with_newline=ends_with_newline,
        )
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        cause = (
            "torn tail: partial write (line lacks trailing newline)"
            if not ends_with_newline
            else "invalid json line (external corruption)"
        )
        return LineCheck(
            lineno, byte_start, byte_end, ok=False, reason="unparseable_json",
            ends_with_newline=ends_with_newline, suspected_cause=cause,
        )
    if not isinstance(value, dict):
        return LineCheck(
            lineno, byte_start, byte_end, ok=False, reason="not_an_object",
            ends_with_newline=ends_with_newline,
            suspected_cause="non-object json line (external corruption)",
        )
    if not line_integrity_matches(value):
        return LineCheck(
            lineno, byte_start, byte_end, ok=False, reason="integrity_mismatch",
            entry=value, ends_with_newline=ends_with_newline,
            suspected_cause="integrity mismatch: line bytes altered after write",
        )
    return LineCheck(
        lineno, byte_start, byte_end, ok=True,
        reason="legacy_no_credential" if not value.get("integrity") else "ok",
        entry=value, ends_with_newline=ends_with_newline,
    )


def scan_ledger(path: Path) -> tuple[list[LineCheck], bytes]:
    """逐行扫描账本（字节偏移精确），返回行检查结果与原始字节。"""
    if not path.is_file():
        return [], b""
    raw = path.read_bytes()
    checks: list[LineCheck] = []
    offset = 0
    lineno = 0
    while offset < len(raw):
        nl = raw.find(b"\n", offset)
        if nl == -1:
            chunk, ends = raw[offset:], False
        else:
            chunk, ends = raw[offset : nl + 1], True
        lineno += 1
        checks.append(_check_line(chunk, lineno, offset, ends))
        offset = len(chunk) + offset if nl == -1 else nl + 1
    return checks, raw


def count_valid_lines(path: Path) -> int:
    checks, _raw = scan_ledger(path)
    return sum(1 for c in checks if c.ok and c.reason != "blank")


def quarantine_torn_tail(path: Path) -> dict:
    """把尾部损坏行移入隔离旁文件并出具诊断报告；主账本截断到最后一条完好记录.

    - 只迁移"最后一条完好记录之后"的损坏行（torn tail）；中段损坏行不动
      （改写中段等于重写账本），但在报告中列出，不静默跳过。
    - 旁文件保留原始字节；报告含行号、字节范围、原因与疑似原因。
    - 调用方必须已持有该账本的单写者锁。
    """
    checks, raw = scan_ledger(path)
    invalid = [c for c in checks if not c.ok]
    if not invalid:
        return {
            "file": str(path),
            "quarantined_count": 0,
            "quarantined": [],
            "midfile_invalid": [],
            "truncated_to_offset": len(raw),
            "ts": system_local_now().isoformat(),
        }

    last_good_end = 0
    for c in checks:
        if c.ok:
            last_good_end = c.byte_end
    quarantined = [c for c in invalid if c.byte_start >= last_good_end]
    midfile = [
        {
            "line": c.lineno,
            "byte_start": c.byte_start,
            "byte_end": c.byte_end,
            "reason": c.reason,
            "suspected_cause": c.suspected_cause,
        }
        for c in invalid
        if c.byte_start < last_good_end
    ]

    sidecar = path.with_name(path.name + _QUARANTINE_SUFFIX)
    moved = raw[last_good_end:]
    if moved:
        with sidecar.open("ab") as fh:
            fh.write(moved)
            fh.flush()
            os.fsync(fh.fileno())
    with open(path, "r+b") as fh:
        fh.truncate(last_good_end)
        fh.flush()
        os.fsync(fh.fileno())

    report = {
        "file": str(path),
        "ts": system_local_now().isoformat(),
        "quarantined_count": len(quarantined),
        "quarantined": [
            {
                "line": c.lineno,
                "byte_start": c.byte_start,
                "byte_end": c.byte_end,
                "reason": c.reason,
                "suspected_cause": c.suspected_cause
                or ("torn tail: partial write" if not c.ends_with_newline else "corrupt line"),
            }
            for c in quarantined
        ],
        "midfile_invalid": midfile,
        "truncated_to_offset": last_good_end,
        "sidecar": str(sidecar),
    }
    report_path = path.with_name(path.name + _QUARANTINE_REPORT_SUFFIX)
    with report_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        fh.flush()
        os.fsync(fh.fileno())
    logger.error(
        "usage ledger torn tail quarantined: %s lines moved to %s (%s)",
        len(quarantined), sidecar, path,
    )
    return report


def ensure_appendable_tail(path: Path) -> dict:
    """追加前守卫：尾部损坏先隔离修复，绝不直接在坏行上追加。"""
    checks, _raw = scan_ledger(path)
    if not any(not c.ok for c in checks):
        return {"quarantined_count": 0}
    return quarantine_torn_tail(path)


def append_ledger_line(path: Path, entry: dict) -> dict:
    """追加一行（带完整性凭据 + fsync），返回实际落盘的条目（含凭据）.

    调用方必须已持有单写者锁；回执与账本行同构（read == write）。
    末行缺换行（外部重写）时先补换行再追加，绝不与既有字节粘连成坏行。
    """
    line = with_line_integrity(entry)
    payload = canonical_json(line) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        try:
            if path.stat().st_size > 0:
                # 以二进制视角核对末字节；文本模式 tell/seek 有编码边界风险
                with path.open("rb") as probe:
                    probe.seek(-1, os.SEEK_END)
                    if probe.read(1) != b"\n":
                        fh.write("\n")
        except OSError:
            pass  # 探测失败不阻断追加（append 模式本身从文件尾写）
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    return line


def read_ledger_entries(path: Path) -> list[dict]:
    """读取全部完好条目（旧→新，文件序=追加序）；损坏行交给恢复扫描处理。"""
    checks, _raw = scan_ledger(path)
    return [c.entry for c in checks if c.ok and c.entry is not None]
