"""Interactive CLI control surface; local commands never become model messages."""
from __future__ import annotations

import json
import shlex
import signal
import sys
import threading
from contextlib import contextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.model_command import handle_model_command
from llm_loop.introspection.task_store import TaskStore
from llm_loop.terminal.approval import ApprovalBridge
from llm_loop.terminal.editor import KEY_HELP, Composer, palette_text
from llm_loop.terminal.execution import run_turn
from llm_loop.terminal.markdown import render_markdown
from llm_loop.terminal.presentation import Presenter, safe_text
from llm_loop.terminal.records import (
    RecordBrowser,
    copy_answer,
    export_record,
    message_detail,
    stored_diff,
    transcript,
)
from llm_loop.terminal.settings import load_ui, save_ui, validate_ui


@contextmanager
def _preinput_signal_guard(composer: Composer):
    """Own terminal signals until the next-turn prompt has actually closed."""
    interrupted = threading.Event()
    terminated = threading.Event()
    if threading.current_thread() is not threading.main_thread():
        yield interrupted, terminated
        return

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)

    def on_interrupt(_signum, _frame):
        interrupted.set()
        with suppress(Exception):
            composer.request_abort_preinput()

    def on_terminate(_signum, _frame):
        terminated.set()
        with suppress(Exception):
            composer.request_abort_preinput()

    signal.signal(signal.SIGINT, on_interrupt)
    signal.signal(signal.SIGTERM, on_terminate)
    try:
        yield interrupted, terminated
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)


def interactive_session(engine: Any, sid: str) -> int:
    try:
        ui = load_ui()
    except (OSError, ValueError, TypeError) as exc:
        print(f"[display settings] {safe_text(exc)}; using defaults.", file=sys.stderr)
        ui = validate_ui({})
    ui.plain = ui.plain or getattr(engine, "_cli_plain", False) or not sys.stdout.isatty()
    if getattr(engine, "_cli_theme", None):
        ui.theme = engine._cli_theme
    composer = Composer(ui, Path(getattr(engine, "_cli_workspace", Path.cwd())))
    approval = getattr(engine, "_cli_approval_bridge", None)
    if approval is None:
        approval = ApprovalBridge()
        engine.registry.set_approval_callback(approval)
    print(f"LFL · session {sid} · /help · /keys · /exit")
    detector = getattr(engine, "loop_signal_detector", None)
    if detector is not None:
        detector.popup_pending_review = True
    queued_text: str | None = None
    try:
        while True:
            _pending_review(engine, detector)
            session = engine.session.load(sid)
            if queued_text is None:
                try:
                    text = composer.read(sid, session.model_override or "")
                except EOFError:
                    return 0
                except KeyboardInterrupt:
                    print("Use Ctrl+D on an empty composer or /exit.")
                    continue
            else:
                # A queued draft is promoted to a user message only after run_turn settled.
                text, queued_text = queued_text, None
            if not text.strip():
                continue
            control = text.strip()
            if control.lower() in {"exit", "quit", "退出", "/exit"}:
                return 0
            if control.lower() in {"/new", "/clear"}:
                sid = engine.session.create(model_override=session.model_override)
                print(f"[new session] {sid}; previous history retained")
                continue
            if control.startswith("/resume "):
                target = control.removeprefix("/resume ").strip()
                if engine.session.exists(target):
                    sid = target
                else:
                    print("[session not found] No replacement session was created.")
                continue
            if _local_command(engine, session, control, composer):
                continue
            context = getattr(engine, "correction_ctx", None)
            if context is not None:
                reply = handle_model_command(text, context, session, engine.session, audit=None)
                if reply is not None:
                    print(safe_text(reply.reply))
                    continue
            if text.startswith("/"):
                print("[unknown command] Use /palette; use a regular message for model input.")
                continue
            preinput = composer if composer.supports_preinput else None
            view = Presenter(plain=ui.plain, width=ui.width)
            if preinput is None:
                # Keep the legacy call shape for plain/non-TTY sessions and injected adapters.
                run_exit = run_turn(engine, sid, text, view, approval, interactive=True)
            else:
                with _preinput_signal_guard(composer) as (draft_interrupted, draft_terminated):
                    run_exit = run_turn(
                        engine, sid, text, view, approval,
                        interactive=True, preinput=preinput, model=session.model_override or "",
                    )
                    if run_exit == 143:
                        return run_exit
                    composer.mark_preinput_run_settled()
                    draft_eof = False
                    try:
                        queued_text = composer.finish_preinput()
                    except EOFError:
                        queued_text, draft_eof = None, True
                    except Exception as exc:  # noqa: BLE001 - current run is already settled
                        print(
                            f"[next-turn draft] {type(exc).__name__}: {safe_text(exc)}; "
                            "the current run remains settled.",
                            file=sys.stderr,
                        )
                        queued_text = None
                    if draft_terminated.is_set():
                        return 143
                    if draft_interrupted.is_set():
                        queued_text = None
                    if draft_eof:
                        return 0
                    if queued_text is not None and not queued_text.strip():
                        queued_text = None
            if run_exit == 143:
                return run_exit
    finally:
        approval.close()


def _pending_review(engine: Any, detector: Any) -> None:
    if detector is None:
        return
    try:
        store = getattr(getattr(engine, "correction_ctx", None), "evolution_store", None)
        detector.check_pending_review(store)
    except Exception as exc:  # noqa: BLE001 - preserve existing explicit maintenance feedback
        print(safe_text(f"[pending review unavailable] {type(exc).__name__}: {exc}"), file=sys.stderr)


def _local_command(engine: Any, session: Any, text: str, composer: Composer) -> bool:
    if not text.startswith("/"):
        return False
    try:
        parts = shlex.split(text)
        name, args = parts[0], parts[1:]
        return _dispatch_local(engine, session, name, args, composer)
    except (ValueError, OSError, IndexError) as exc:
        print(safe_text(f"[command error] {type(exc).__name__}: {exc}"), file=sys.stderr)
        return True


def _dispatch_local(engine: Any, session: Any, name: str, args: list[str], composer: Composer) -> bool:
    if name == "/help":
        print(palette_text())
    elif name in {"/palette", "/commands"}:
        selected = composer.select_command()
        if selected and not composer.draft:
            composer.draft = selected + " "
            print(f"Selected {selected}; edit and explicitly submit to run the local action.")
        elif selected:
            print(f"Selected {selected}; preserved your existing draft. "
                  f"Use {selected} after sending or stashing it.")
        else:
            # Plain/SSH/dumb terminals retain full keyboard-discoverable text fallback.
            print(palette_text())
    elif name == "/keys":
        print(KEY_HELP)
        print("User overrides: " + json.dumps(composer.ui.keybindings, ensure_ascii=False))
    elif name == "/keymap":
        from llm_loop.terminal.settings import keymap_report
        print(keymap_report(composer.ui))
    elif name == "/input":
        if args not in (["single"], ["multiline"]):
            raise ValueError("/input single|multiline")
        composer.ui.multiline = args == ["multiline"]
        print(f"Input mode: {args[0]}")
    elif name == "/theme":
        theme = composer.saved_theme if args == ["cancel"] else args[0]
        composer.ui = validate_ui(asdict(composer.ui) | {"theme": theme})
        print(f"Theme preview: {composer.ui.theme}; /settings save persists it.")
    elif name == "/settings":
        if args == ["save"]:
            save_ui(composer.ui)
            composer.saved_theme = composer.ui.theme
            print("Saved user display preferences.")
        elif args == ["reset"]:
            composer.ui = validate_ui({})
            composer.sessions.clear()
            print("Display defaults restored for this shell; /settings save persists them.")
        elif args[:1] == ["bind"] and len(args) >= 2:
            bindings = composer.ui.keybindings | {args[1]: args[2:]}
            composer.ui = validate_ui(asdict(composer.ui) | {"keybindings": bindings})
            composer.sessions.clear()
            print("Binding preview applied; /settings save persists it."
                  if args[2:] else "Action disabled in this shell; /settings save persists it.")
        elif len(args) == 2 and args[0] == "unbind":
            bindings = composer.ui.keybindings | {args[1]: []}
            composer.ui = validate_ui(asdict(composer.ui) | {"keybindings": bindings})
            composer.sessions.clear()
            print("Action disabled in this shell; /settings save persists it.")
        elif args == ["keymap-reset"]:
            composer.ui = validate_ui(asdict(composer.ui) | {"keybindings": {}})
            composer.sessions.clear()
            print("Default keybindings restored; /settings save persists them.")
        else:
            print(json.dumps(asdict(composer.ui), ensure_ascii=False, indent=2))
    elif name in {"/transcript", "/raw", "/details", "/diff", "/copy", "/export"}:
        _record_command(session.to_dict(), name, args)
    elif name == "/browse":
        cursor = composer.record_views.setdefault(session.session_id, RecordBrowser())
        print(safe_text(cursor.navigate(session.to_dict(), args)))
    elif name == "/sessions":
        for row in engine.session.list_sessions():
            print(safe_text(f"{row.session_id}  {row.title}  {row.message_count} messages"))
    elif name == "/tasks":
        print(safe_text(json.dumps(task_snapshot(engine, session.session_id), ensure_ascii=False, indent=2)))
    elif name == "/draft":
        composer.swap_draft()
        print("Draft restored/stashed locally.")
    elif name == "/history":
        history = composer.history.get(session.session_id)
        print(safe_text("\n".join(history.get_strings()) if history else "No input history in this shell."))
    elif name == "/editor":
        composer.external_edit()
    elif name == "/render":
        answer = next((message.content for message in reversed(session.messages)
                       if message.role == "assistant"), "")
        render_markdown(answer, composer.ui.width, composer.ui.plain)
    elif name == "/redraw":
        pass  # prompt_toolkit redraws the next composer; transcript remains terminal-owned
    elif name == "/stop":
        print("No CLI-owned run is active at the composer. During a run use Ctrl+C.")
    else:
        return False
    return True


def _record_command(raw: dict, name: str, args: list[str]) -> None:
    if name == "/raw":
        print(safe_text(json.dumps(raw, ensure_ascii=False, indent=2)))
    elif name == "/transcript":
        print(safe_text(transcript(raw)))
    elif name in {"/details", "/diff"}:
        # A diff is stored content, never a reconstructed/guessed patch.
        index = int(args[0]) if args else None
        print(safe_text(stored_diff(raw, index) if name == "/diff" else message_detail(raw, index)))
    elif name == "/copy":
        copy_answer(raw)
    elif name == "/export":
        if len(args) != 2 or args[0] not in {"json", "markdown"}:
            raise ValueError("/export json|markdown NEW_FILE")
        export_record(raw, Path(args[1]).expanduser(), args[0])
        print("Exported exact stored content to a new file.")


def task_snapshot(engine: Any, sid: str) -> dict:
    audit = getattr(getattr(engine, "settings", None), "audit_dir", None)
    report = {"session_id": sid, "goal": None, "tasks": [], "children": None}
    if audit is not None and Path(audit).is_dir():
        goal = GoalStore(audit).get(prefer_session_id=sid, strict_session=True)
        report["goal"] = goal
        if goal is not None and (Path(audit) / "tasks").is_dir():
            goal_id = goal.get("id") if isinstance(goal, dict) else None
            if isinstance(goal_id, str) and goal_id.strip():
                report["tasks"] = [
                    asdict(task) for task in TaskStore(audit).list_for_goal(goal_id)
                ]
            else:
                report["tasks_error"] = "Goal record has no valid id"
    runner = getattr(engine, "subagent_runner", None)
    if runner is not None:
        ok, detail, view = runner.topology_lease_view(parent_id=sid)
        report["children"] = view if ok else {"unavailable": detail}
    return report
