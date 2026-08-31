#!/usr/bin/env python3
"""泄漏证据取回与脱敏回归 fixture 制作（tasks 1.1，spec 5.1.1-2）.

从归档证据文件 data/event_logs/004976ea-*.jsonl（只读）提取 msg #280/#290
泄漏原文及同构重放对 #282-284/#292-296 检索动作，脱敏后落
tests/fixtures/trace_leak/（kebab-case）。归档会话本体零改动。

脱敏原则：去除真实 EVO 编号/路径/引用指纹，保留结构特征
（思考过程标记 + 工具调用命令组合 + user 身份零/伪 metadata 形态），
且替换全部为确定性映射（同输入恒同输出）——脚本二次运行产出逐字节一致（幂等验收）。

用法：python3 scripts/forensics/extract_leak_fixture.py [repo_root]
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

SOURCE_REL = "data/event_logs/004976ea-5a23-4ae9-9f16-83b18767720a.jsonl"
OUT_DIR_REL = "tests/fixtures/trace_leak"

LEAK_MSG_INDEXES = (280, 290)
REPLAY_PAIR_INDEXES = (281, 282, 283, 284, 291, 292, 293, 294, 295, 296)

# ── 确定性脱敏规则（幂等：同输入恒同输出） ──────────────────────────────

_RE_EVO = re.compile(r"EVO-\d{8}-[0-9a-f]{8}")
_RE_HEX_LONG = re.compile(r"\b[0-9a-f]{24,}\b")
_RE_HEX_SHORT = re.compile(r"(?<=[（(=、\s])[0-9a-f]{8}(?=[=）)、\s]|$)")
_RE_REF_EVIDENCE = re.compile(r"evidence://v1/[0-9a-f]+")
_RE_USER_PATH = re.compile(r"/Users/[^\s\"'，。；)）]+")
_RE_EVENT_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)

_SESSION_ID = "004976ea-5a23-4ae9-9f16-83b18767720a"
_REDACTED_SESSION = "00000000-0eak-0000-0000-000000000280"


class _Redactor:
    """确定性序号脱敏器：同值恒映射同一编号，跨字段稳定。"""

    def __init__(self) -> None:
        self._evo: dict[str, str] = {}
        self._hex: dict[str, str] = {}
        self._ref: dict[str, str] = {}
        self._path: dict[str, str] = {}

    def evo(self, m: re.Match[str]) -> str:
        key = m.group(0)
        if key not in self._evo:
            self._evo[key] = f"EVO-REDACTED-{len(self._evo) + 1:08d}"
        return self._evo[key]

    def hex(self, m: re.Match[str]) -> str:
        key = m.group(0)
        if key not in self._hex:
            n = len(self._hex) + 1
            self._hex[key] = f"redacted{n:04d}".ljust(len(key), "0")[: len(key)]
        return self._hex[key]

    def hex_short(self, m: re.Match[str]) -> str:
        key = m.group(0)
        if key not in self._hex:
            n = len(self._hex) + 1
            self._hex[key] = f"h{n:07d}"
        return self._hex[key]

    def ref(self, m: re.Match[str]) -> str:
        key = m.group(0)
        if key not in self._ref:
            n = len(self._ref) + 1
            self._ref[key] = "evidence://v1/" + (f"r{n:04d}" + "0" * 16)[:24]
        return self._ref[key]

    def path(self, m: re.Match[str]) -> str:
        key = m.group(0)
        if key not in self._path:
            n = len(self._path) + 1
            self._path[key] = f"/redacted/path{n}"
        return self._path[key]

    def event_id(self, stable_key: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"leak-fixture:{stable_key}"))

    def redact_text(self, text: str) -> str:
        out = _RE_EVO.sub(self.evo, text)
        out = _RE_REF_EVIDENCE.sub(self.ref, out)
        out = _RE_USER_PATH.sub(self.path, out)
        out = _RE_HEX_LONG.sub(self.hex, out)
        out = _RE_HEX_SHORT.sub(self.hex_short, out)
        return out


def _load_events(repo: Path) -> list[dict]:
    src = repo / SOURCE_REL
    events: list[dict] = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def _redact_event(ev: dict, redactor: _Redactor, seq_key: str) -> str:
    """脱敏单条事件并返回定长 JSON 行（键序稳定 → 字节级幂等）。"""
    payload = ev.get("payload") or {}
    redacted_payload: dict = {}
    for k, v in payload.items():
        if k == "content":
            redacted_payload[k] = redactor.redact_text(str(v or ""))
        elif k == "metadata":
            # 结构保真：零/伪 metadata 形态是判定输入，原样保留
            redacted_payload[k] = v
        elif isinstance(v, str):
            redacted_payload[k] = redactor.redact_text(v)
        else:
            redacted_payload[k] = v
    out = {
        "event_id": redactor.event_id(seq_key),
        "session_id": _REDACTED_SESSION,
        "seq": ev.get("seq", 0),
        "type": ev.get("type", ""),
        "ts": ev.get("ts", ""),
        "payload": redacted_payload,
    }
    return json.dumps(out, ensure_ascii=False, sort_keys=False, separators=(", ", ": "))


def main(repo_root: str = ".") -> int:
    repo = Path(repo_root)
    events = _load_events(repo)
    redactor = _Redactor()
    out_dir = repo / OUT_DIR_REL
    out_dir.mkdir(parents=True, exist_ok=True)

    by_index: dict[int, dict] = {}
    for ev in events:
        p = ev.get("payload") or {}
        idx = p.get("index")
        if isinstance(idx, int):
            by_index.setdefault(idx, ev)

    products: dict[str, list[str]] = {
        "leak-280-msg.jsonl": [],
        "leak-290-msg.jsonl": [],
        "isomorphic-replay-pair.jsonl": [],
    }
    for idx in LEAK_MSG_INDEXES:
        ev = by_index.get(idx)
        if ev is None:
            print(f"[miss] msg #{idx} 未找到", file=sys.stderr)
            return 2
        name = f"leak-{idx}-msg.jsonl"
        products[name].append(_redact_event(ev, redactor, f"msg-{idx}"))

    for idx in REPLAY_PAIR_INDEXES:
        ev = by_index.get(idx)
        if ev is None:
            print(f"[miss] replay msg #{idx} 未找到", file=sys.stderr)
            return 2
        products["isomorphic-replay-pair.jsonl"].append(
            _redact_event(ev, redactor, f"replay-{idx}")
        )

    for name, lines in products.items():
        target = out_dir / name
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[ok] {target} ({len(lines)} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
