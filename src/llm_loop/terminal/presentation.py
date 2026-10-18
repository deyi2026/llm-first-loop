"""Lossless output contracts and safe terminal presentation."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, is_dataclass
from typing import Any

# Escape every terminal control, including OSC/DCS/CSI, rather than executing it.
# Newlines/tabs remain readable. Exact originals live in session/JSON/export.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def safe_text(value: object) -> str:
    return _CONTROL.sub(lambda m: f"\\x{ord(m[0]):02x}", str(value))


def result_status(result: Any) -> tuple[str, int]:
    if getattr(result, "cancel_reason", ""):
        return "cancelled", 1
    if any(getattr(result, key, False) for key in (
        "run_incomplete", "provider_output_truncated", "projection_cannot_fit",
    )):
        return "incomplete", 1
    return "completed", 0


def result_record(result: Any, generation: str = "") -> dict:
    fields = (
        "session_id", "final_answer", "rounds", "model_used", "tokens_in", "tokens_out",
        "tokens_cache_hit", "history_compacted", "run_incomplete",
        "provider_output_truncated", "projection_cannot_fit", "cancel_reason",
        "fallback_receipt", "verification_note",
    )
    status, code = result_status(result)
    return {"schema": "lfl.cli/v1", "type": "result", "run_generation": generation,
            "status": status, "exit_code": code,
            **{name: getattr(result, name, None) for name in fields}}


class Presenter:
    """stdout is the selected result protocol; diagnostics always use stderr."""

    def __init__(self, mode: str = "text", *, stream: bool = True, plain: bool = False):
        self.mode = mode
        self.stream = stream
        self.plain = plain or not sys.stdout.isatty()
        self.text = ""
        self.generation = ""
        self.session_id = ""
        self.seq = 0

    def event(self, kind: str, **values: Any) -> None:
        if self.mode != "jsonl":
            return
        self.seq += 1
        print(json.dumps({"schema": "lfl.cli/v1", "type": kind, "seq": self.seq,
                          "session_id": self.session_id, "run_generation": self.generation,
                          **values}, ensure_ascii=False), flush=True)

    def started(self, sid: str, generation: str) -> None:
        self.session_id, self.generation = sid, generation
        self.event("run_started")

    def delta(self, delta: Any) -> None:
        if delta.text:
            self.text += delta.text
            self.event("text_delta", text=delta.text)
            if self.mode == "text" and self.stream:
                print(safe_text(delta.text), end="", flush=True)
        for attr, kind in (("tool_round", "tool_started"), ("tool_result", "tool_finished")):
            info = getattr(delta, attr, None)
            if info is not None:
                # Arguments are available through explicit details; never print secrets
                # from args_summary in the default status display.
                values = asdict(info) if is_dataclass(info) and not isinstance(info, type) else {}
                values.pop("args_summary", None)
                self.event(kind, **values)
                if self.mode == "text":
                    label = getattr(info, "tool_name", "tool")
                    status = getattr(info, "status", "running")
                    print(f"\n[tool {safe_text(label)}: {safe_text(status)}]", file=sys.stderr, flush=True)
        if getattr(delta, "reasoning", None):
            self.event("reasoning_activity")  # presence, never a fabricated token count

    def notice(self, text: str) -> None:
        print(safe_text(text), file=sys.stderr, flush=True)

    def finish(self, result: Any, *, exit_code: int | None = None) -> int:
        record = result_record(result, self.generation)
        if exit_code is not None:
            record["exit_code"] = exit_code
        if self.mode == "json":
            print(json.dumps(record, ensure_ascii=False), flush=True)
        elif self.mode == "jsonl":
            values = {k: v for k, v in record.items()
                      if k not in {"schema", "type", "session_id", "run_generation"}}
            self.event("result", **values)
        else:
            answer = result.final_answer
            if not self.stream or not self.text.endswith(answer) or not self.text:
                if self.text and self.stream:
                    print()
                print(safe_text(answer), end="", flush=True)
            print()
            facts = f"[{record['status']}] session={result.session_id} model={getattr(result, 'model_used', '') or 'unreported'}"
            facts += f" rounds={getattr(result, 'rounds', 0)}"
            facts += f" tokens={getattr(result, 'tokens_in', 0)}/{getattr(result, 'tokens_out', 0)}"
            self.notice(facts)
            for key in ("provider_output_truncated", "projection_cannot_fit", "cancel_reason", "verification_note"):
                value = getattr(result, key, None)
                if value:
                    self.notice(f"{key}: {value}")
            if result.fallback_receipt:
                self.notice(f"fallback: {result.fallback_receipt}")
        return record["exit_code"]

    def error(self, message: str, code: str = "run_error", exit_code: int = 1) -> int:
        if self.mode == "jsonl":
            self.event("error", error_code=code, message=message, exit_code=exit_code)
        elif self.mode == "json":
            print(json.dumps({"schema": "lfl.cli/v1", "type": "error",
                              "session_id": self.session_id, "run_generation": self.generation,
                              "error_code": code, "message": message, "exit_code": exit_code},
                             ensure_ascii=False), flush=True)
        else:
            self.notice(f"[{code}] {message}")
        return exit_code
