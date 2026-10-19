"""Lossless output contracts and safe terminal presentation."""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, is_dataclass
from typing import Any

from llm_loop.runtime.resolver import legacy_env_snapshot
from llm_loop.terminal.text import safe_text


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

    def __init__(self, mode: str = "text", *, stream: bool = True, plain: bool = False,
                 width: int = 100):
        self.mode = mode
        self.stream = stream
        self.plain = plain or not sys.stdout.isatty() or legacy_env_snapshot().get("TERM") == "dumb"
        # Rich blocks are a TTY projection; piped text and JSON protocols are unchanged.
        self._markdown = None
        if mode == "text" and stream and not self.plain:
            # Markdown depends on safe_text from this module; import after it is defined.
            from llm_loop.terminal.markdown import IncrementalMarkdown
            self._markdown = IncrementalMarkdown(width)
        self.text = ""
        self.generation = ""
        self.session_id = ""
        self.seq = 0
        self.activity_hook: Callable[[], None] | None = None

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
        hook = self.activity_hook
        if hook is not None:
            with suppress(Exception):  # UI observation must not abort a running model
                hook()
        if delta.text:
            self.text += delta.text
            self.event("text_delta", text=delta.text)
            if self.mode == "text" and self.stream:
                if self._markdown is not None:
                    self._markdown.feed(delta.text)
                else:
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
                    if self._markdown is not None:
                        self._markdown.flush_before_status()
                    label = getattr(info, "tool_name", "tool")
                    status = getattr(info, "status", "running")
                    print(f"\n[tool {safe_text(label)}: {safe_text(status)}]", file=sys.stderr, flush=True)
        if getattr(delta, "reasoning", None):
            self.event("reasoning_activity")  # presence, never a fabricated token count

    def use_raw_stream(self) -> None:
        """Compatibility runner has no idle event pump: never buffer its deltas."""
        self._markdown = None

    def tick(self) -> None:
        """Main-thread idle pump keeps unclosed paragraphs responsive."""
        if self._markdown is not None:
            self._markdown.flush_due()

    def notice(self, text: str) -> None:
        if self._markdown is not None:
            self._markdown.flush_before_status()
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
            if self._markdown is not None:
                self._markdown.finish()
            answer = result.final_answer
            if not self.stream or not self.text.endswith(answer) or not self.text:
                if self.text and self.stream:
                    print()
                if self._markdown is not None:
                    from llm_loop.terminal.markdown import render_markdown
                    render_markdown(answer, width=self._markdown.width)
                else:
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
        if self._markdown is not None:
            self._markdown.finish()
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
