#!/usr/bin/env python3
"""claim/fanout 观测口径（DESIGN-20261103 §6.6 / §11.3）.

为什么单独一个脚本而不是埋在 web UI 里：这几个比率是**观察期决策输入**
（fanout 闸 16 是否合适、claim 冲突是不是常态），要能对着一个 audit 目录
离线重算、能贴进文档，而不是只能看实时面板。

口径约定（写清楚比数字更重要）：
- 分母**只统计实际发生过决策的事件**。``claims/events.jsonl`` 缺失或含坏行时
  标 ``degraded=true`` 并给出坏行数——分母不完整时任何比率都只是下界。
- ``claim_conflict_rate`` 的分母是**不带 token 的写入**：带 token 的写入本来就
  受 fencing 保护，把它们算进分母会稀释真实的"未受保护写入"占比。
- PR-1 的 ``claim_enforcement=warn``：冲突只记事件不拒绝，所以这里的冲突率
  等于"本该被 fencing 拦下的写入"的实际发生率。

用法：
    python3 scripts/claim_metrics.py [--audit-dir DIR] [--json]
    缺省 audit dir 取 LFL_AUDIT_DIR，再缺省 <repo>/audit。
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MAX_TAIL_BYTES = 32 * 1024 * 1024


def _events_path(audit_dir: Path) -> Path:
    return audit_dir / "claims" / "events.jsonl"


def _read_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    """读事件流；只做有界尾读（事件流尚无轮转，见 R19）."""
    if not path.exists():
        return [], 0
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > MAX_TAIL_BYTES:
            fh.seek(size - MAX_TAIL_BYTES)
            fh.readline()  # 丢掉被截断的首行
        blob = fh.read().decode("utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    bad = 0
    for line in blob.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    return rows, bad


_SINCE_RE = re.compile(r"^(\d+)([dhms])$")


def _parse_since(raw: str | None) -> datetime | None:
    """``--since 7d`` / ``24h`` / ``90m`` / ISO8601。非法值直接报错，不静默忽略."""
    if not raw:
        return None
    m = _SINCE_RE.match(raw.strip())
    now = datetime.now().astimezone()
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        return now - {
            "d": timedelta(days=amount),
            "h": timedelta(hours=amount),
            "m": timedelta(minutes=amount),
            "s": timedelta(seconds=amount),
        }[unit]
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise SystemExit(f"--since 无法解析: {raw!r}（支持 7d/24h/90m 或 ISO8601）") from exc
    return parsed if parsed.tzinfo else parsed.astimezone()


def _row_at(row: dict[str, Any]) -> datetime | None:
    raw = row.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _ledger_stats(audit_dir: Path) -> dict[str, Any]:
    """claims 账本侧的机械计数（与事件流互为交叉校验，不互相替代）."""
    files = sorted((audit_dir / "claims").glob("claim-*.jsonl")) if (audit_dir / "claims").exists() else []
    rows = bad = 0
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            rows += 1
    return {"files": len(files), "rows": rows, "bad_rows": bad}


def _rate(num: int, den: int) -> float | None:
    """分母为 0 时返回 None（不是 0）——没有样本 ≠ 比率是 0."""
    return round(num / den, 4) if den else None


def compute(audit_dir: Path, *, since: datetime | None = None) -> dict[str, Any]:
    claim_rows, bad_lines = _read_rows(_events_path(audit_dir))
    if since is not None:
        claim_rows = [r for r in claim_rows if (ts := _row_at(r)) is not None and ts >= since]
    claims = [r for r in claim_rows if r.get("kind") == "claim_decision"]
    fans = [r for r in claim_rows if r.get("kind") == "fanout_decision"]

    decisions = Counter(str(r.get("decision") or "?") for r in claims)
    reason_codes = Counter(str(r.get("reason_code")) for r in claims if r.get("reason_code"))
    fan_outcomes = Counter(str(r.get("decision") or "?") for r in fans)
    fan_reasons = Counter(str(r.get("reason_code")) for r in fans if r.get("reason_code"))

    protected = sum(1 for r in claims if r.get("claim_generation"))
    unprotected = sum(1 for r in claims if not r.get("claim_generation"))
    conflict_rows = [
        r for r in claims if r.get("reason_code") in {"claim_held_by_other", "claim_conflict"}
    ]

    result: dict[str, Any] = {
        "audit_dir": str(audit_dir),
        "events": {
            "total": len(claim_rows),
            "claim_decision": len(claims),
            "fanout_decision": len(fans),
            "bad_lines": bad_lines,
        },
        "claim": {
            "by_decision": dict(decisions),
            "by_reason_code": dict(reason_codes),
            "grant_rate": _rate(decisions.get("grant", 0) + decisions.get("reclaim", 0), len(claims)),
            "renew_rate": _rate(decisions.get("renew", 0), len(claims)),
            "revoke_count": decisions.get("revoke", 0),
            "auto_claim_share": _rate(sum(1 for r in claims if r.get("auto")), len(claims)),
            "unprotected_write_share": _rate(unprotected, protected + unprotected),
            "conflict_count": len(conflict_rows),
            "conflict_rate_of_unprotected": _rate(len(conflict_rows), unprotected),
            "latency_ms_median": _median([r.get("latency_ms") for r in claims if isinstance(r.get("latency_ms"), (int, float))]),
        },
        "fanout": {
            "by_decision": dict(fan_outcomes),
            "by_reason_code": dict(fan_reasons),
            "deny_rate": _rate(fan_outcomes.get("deny", 0), len(fans)),
            "parent_concurrency_deny_rate": _rate(fan_reasons.get("parent_concurrency", 0), len(fans)),
        },
        "claim_ledger": _ledger_stats(audit_dir),
        "since": since.isoformat(timespec="seconds") if since else None,
        "degraded": bool(bad_lines),
        "notes": [],
    }
    if bad_lines:
        result["notes"].append(f"事件流含 {bad_lines} 个坏行已跳过：比率是下界，不是精确值")
    if not claims and not fans:
        result["notes"].append("没有决策事件：分母为空，所有比率为 null（不代表 0）")
    if result["claim"]["unprotected_write_share"] is not None and result["claim"]["unprotected_write_share"] > 0:
        result["notes"].append(
            "存在未带 claim token 的写入：PR-1 是 warn 模式，这些写入不受 fencing 保护"
        )
    return result


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 3)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 3)


def render(result: dict[str, Any]) -> str:
    lines = [f"audit_dir: {result['audit_dir']}"]
    ev = result["events"]
    lines.append(
        f"事件: total={ev['total']} claim={ev['claim_decision']} fanout={ev['fanout_decision']} bad_lines={ev['bad_lines']}"
    )
    c = result["claim"]
    lines.append(
        "claim: "
        f"grant={c['by_decision'].get('grant', 0)} renew={c['by_decision'].get('renew', 0)} "
        f"reclaim={c['by_decision'].get('reclaim', 0)} revoke={c['by_decision'].get('revoke', 0)} "
        f"passthrough={c['by_decision'].get('passthrough', 0)}"
    )
    lines.append(
        f"  未受 fencing 保护写入占比: {c['unprotected_write_share']}  "
        f"冲突/未保护写入: {c['conflict_rate_of_unprotected']}（冲突 {c['conflict_count']} 次）  "
        f"auto_claim 占比: {c['auto_claim_share']}"
    )
    lines.append(f"  写入延迟中位数: {c['latency_ms_median']} ms（取锁→append 完成）")
    f = result["fanout"]
    lines.append(
        f"fanout: allow={f['by_decision'].get('allow', 0)} deny={f['by_decision'].get('deny', 0)} "
        f"deny_rate={f['deny_rate']} parent_concurrency={f['parent_concurrency_deny_rate']}"
    )
    ledger = result["claim_ledger"]
    lines.append(
        f"claim 账本: files={ledger['files']} rows={ledger['rows']} bad_rows={ledger['bad_rows']}"
        "（账本行数与事件行数不必相等：passthrough 写入没有账本行）"
    )
    if result.get("since"):
        lines.append(f"时间窗: since {result['since']}")
    if result["degraded"]:
        lines.append("⚠ degraded: 分母不完整")
    for note in result["notes"]:
        lines.append(f"note: {note}")
    return "\n".join(lines)


def _default_audit_dir() -> str:
    """缺省 audit 目录：``LFL_AUDIT_DIR`` → ``<repo>/data/audit``。

    2026-11-03 审查指出 ``Path.cwd()/audit`` 与运行时布局不符：本仓 ``data_dir``
    默认为 ``<代码根>/data``（config.py ``_DEFAULT_DATA_DIR``），所以真实账本在
    ``<repo>/data/audit``。``cwd`` 口径会让脚本在别处运行时静默读到空目录，
    产出"诚实的 null"，掩盖"根本没读到数据"这件事。
    """
    env_dir = (os.environ.get("LFL_AUDIT_DIR") or "").strip()
    if env_dir:
        return env_dir
    repo_root = Path(__file__).resolve().parents[1]
    return str(repo_root / "data" / "audit")


def main() -> int:
    ap = argparse.ArgumentParser(description="claim/fanout 观测口径")
    ap.add_argument("--audit-dir", default=_default_audit_dir())
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是人类可读表")
    ap.add_argument("--since", default=None, help="只统计该时间窗内的事件（7d/24h/90m 或 ISO8601）")
    args = ap.parse_args()
    result = compute(Path(args.audit_dir).expanduser(), since=_parse_since(args.since))
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
