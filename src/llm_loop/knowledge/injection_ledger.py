"""P0 injection observation ledger (EVO-20260917-abdb3247).

Append-only JSONL observation of knowledge-injection surfaces:
- receipt_pointer rows: advisory/guidance text that actually entered model-visible
  receipt content (LFL_TOOL_GUIDANCE on/shadow; off mode never triggers);
- hydration rows: successful search_records / skill_load executions.

Design constraints (DESIGN-20260917-knowledge-injection-layering P0):
- zero model-visible behavior change (post-hoc observation only);
- fail-open everywhere (any error swallowed; action truth never affected);
- KNOWLEDGE_INJECTION_LEDGER=0 disables all writes (rollback / kill switch);
- INJECTION_LEDGER_PATH overrides the file location (tests / ops).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_LEDGER_PATH: Path | None = None


def _switch_enabled() -> bool:
    raw = (os.environ.get("KNOWLEDGE_INJECTION_LEDGER", "1") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _resolved_path() -> Path:
    # 优先级：显式环境 override（测试/运维）> factory configure 绑定 > 包位置默认。
    # 2026-09-18 全量顺序暴露：configure 的模块级固化一旦先行（任一前置测试
    # build_engine），env override 被短路，ledger 写到错误文件且测试/运维无法
    # 重定向——override 必须永远最高（与 KNOWLEDGE_INJECTION_LEDGER 开关同语义层级）。
    override = (os.environ.get("INJECTION_LEDGER_PATH", "") or "").strip()
    if override:
        return Path(override)
    if _LEDGER_PATH is not None:
        return _LEDGER_PATH
    # Fallback：包位置锚定（factory 已绑定运行时 data_dir 时不会走到这里）
    return Path(__file__).resolve().parents[3] / "data" / "audit" / "injection_ledger.jsonl"


def configure(audit_dir: str | os.PathLike[str]) -> None:
    """Factory 绑定运行时 audit 目录（调用方负责 fail-open 包裹）."""
    global _LEDGER_PATH
    _LEDGER_PATH = Path(audit_dir) / "injection_ledger.jsonl"


def append_row(**fields: Any) -> None:
    """Single-line JSONL append. All failures swallowed by design."""
    try:
        if not _switch_enabled():
            return
        path = _resolved_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": round(time.time(), 3), "pid": os.getpid(), **fields}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - observation must never affect action truth
        return
