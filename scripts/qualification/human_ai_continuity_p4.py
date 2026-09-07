#!/usr/bin/env python3
"""P4 Human-AI Continuity one-model sequential handoff qualification.

This runner is intentionally an experiment harness, not runtime policy. It never injects
an automatic continuation summary. The resumed model receives the durable session plus
the literal user continuation text and may inspect file/effect facts using existing tools.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from llm_loop.config import Settings, load_env_file, load_settings
from llm_loop.factory import build_engine
from llm_loop.workspace.human_file_ops import HumanFileOperationError

WORKSPACE_ID = "p4-human-ai-continuity"
AI_MARKER = "AI_MARKER: completed"
HUMAN_NOTE = "HUMAN_NOTE: preserve-this"
HARD_EXIT_CODE = 73

INITIAL_PROMPT = """Human-AI Continuity P4 资格实验。工作区中有 item1.txt 到 item6.txt 六个普通文本文件。总任务是：对每个文件只做以下变更：把唯一的 `STATUS: pending` 改成 `STATUS: reviewed`，并紧接着新增一行且仅一行 `AI_MARKER: completed`；其余已有内容必须保持原样，已有人工新增内容也必须保留。已经满足条件的文件不要重复修改。

文件修改的机械要求：每次写入前先用 read_file(path=<工作区相对路径>, snapshot=true) 物理读取当前完整文件，再把该次返回的 snapshot_ref 原样作为 edit_file.expected_snapshot_ref；read_file/edit_file 的 path 始终使用 itemN.txt 这种工作区相对路径，不转换成绝对路径；不要用 execute_command、Python、sed 等旁路修改文件。

这是第一段工作：现在只处理 item1.txt 和 item2.txt，确认两项成功后立即停止，不处理 item3.txt 到 item6.txt。之后用户会再让你继续。"""

RESUME_PROMPT = "继续完成刚才的任务，保留我的修改。"



def _settings(runtime: Path) -> Settings:
    """Build an isolated qualification config without persisting credentials.

    The caller must supply all three P4_* variables: an env file, a provider-registry
    JSON file, and an exact model ref. Registry metadata stores key *names* only; secret
    values remain environment-only and are never written into the qualification report.
    """
    env_file = os.environ.get("P4_ENV_FILE", "").strip()
    registry_file = os.environ.get("P4_PROVIDER_REGISTRY_FILE", "").strip()
    model_ref = os.environ.get("P4_MODEL_REF", "").strip()
    if not (env_file and registry_file and model_ref):
        raise RuntimeError(
            "P4 qualification requires P4_ENV_FILE, "
            "P4_PROVIDER_REGISTRY_FILE, and P4_MODEL_REF"
        )
    load_env_file(env_file)
    raw_registry = Path(registry_file).read_text(encoding="utf-8")
    base = load_settings()
    return dataclasses.replace(
        base,
        data_dir=str(runtime / "data"),
        llm_model=model_ref,
        model_providers_raw=raw_registry,
        model_fallbacks_raw="",
        max_iterations=30,
        llm_timeout_s=180.0,
        tool_timeout_s=60.0,
        cache_hit_show_in_answer=False,
        summary_mode="off",
        evidence_mode="off",
        run_mode="standard",
        tool_schema_lazy=True,
    )


def _engine(runtime: Path):
    os.environ["LMS_DIRECT"] = "0"
    os.environ["LLM_TRUST_ENV"] = "0"
    os.environ["LFL_LEAK_GUARD_MODE"] = "observe"
    engine = build_engine(_settings(runtime))
    engine.set_workspace(str(runtime / "workspace"), workspace_id=WORKSPACE_ID)
    return engine


def _write_fixture(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for idx in range(1, 7):
        (workspace / f"item{idx}.txt").write_text(
            f"ITEM: {idx}\nSTATUS: pending\nKEEP: keep-{idx}\n",
            encoding="utf-8",
        )


def _read_state(runtime: Path) -> dict[str, Any]:
    return json.loads((runtime / "state.json").read_text(encoding="utf-8"))


def _write_state(runtime: Path, state: dict[str, Any]) -> None:
    (runtime / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_facts(result) -> dict[str, Any]:
    return {
        "rounds": result.rounds,
        "model_used": result.model_used,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "tokens_cache_hit": result.tokens_cache_hit,
        "reasoning_effective": result.reasoning_effective,
        "reasoning_tokens": result.reasoning_tokens,
        "final_answer": result.final_answer,
        "tool_calls": result.tool_calls,
    }


def _setup(runtime: Path) -> None:
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    _write_fixture(runtime / "workspace")
    engine = _engine(runtime)
    sid = engine.session.create()
    human = engine.human_file_operations
    assert human is not None
    stale = human.observe(
        session_id=sid,
        workspace_scope=str(runtime / "workspace"),
        relative_path="item1.txt",
    )
    _write_state(
        runtime,
        {
            "session_id": sid,
            "stale_item1_snapshot_ref": stale.snapshot_ref,
            "stale_item1_content": stale.content,
        },
    )


def _initial(runtime: Path) -> None:
    state = _read_state(runtime)
    engine = _engine(runtime)
    sid = str(state["session_id"])
    if not engine.session.exists(sid):
        raise RuntimeError("original session missing before initial run")
    result = engine.run(sid, INITIAL_PROMPT)
    state["initial"] = _run_facts(result)
    _write_state(runtime, state)


def _human_hard_exit(runtime: Path) -> None:
    state = _read_state(runtime)
    sid = str(state["session_id"])
    workspace = runtime / "workspace"
    engine = _engine(runtime)
    human = engine.human_file_operations
    assert human is not None

    item2 = human.observe(
        session_id=sid, workspace_scope=str(workspace), relative_path="item2.txt"
    )
    human_receipt = human.edit(
        session_id=sid,
        workspace_scope=str(workspace),
        request_id="p4-real-human-item2",
        relative_path="item2.txt",
        expected_snapshot_ref=item2.snapshot_ref,
        content=item2.content + HUMAN_NOTE + "\n",
        file_contract_version=1,
    )

    stale_conflict = False
    try:
        human.edit(
            session_id=sid,
            workspace_scope=str(workspace),
            request_id="p4-real-stale-item1",
            relative_path="item1.txt",
            expected_snapshot_ref=str(state["stale_item1_snapshot_ref"]),
            content=str(state["stale_item1_content"]) + "STALE: must-not-land\n",
            file_contract_version=1,
        )
    except HumanFileOperationError as exc:
        stale_conflict = exc.code == "version_conflict"
        if not stale_conflict:
            raise

    state["human"] = {
        "operation_id": human_receipt.operation_id,
        "effect_state": human_receipt.effect_state,
        "receipt_state": human_receipt.receipt_state,
        "stale_item1_conflict": stale_conflict,
    }
    _write_state(runtime, state)
    # Deliberately bypass graceful interpreter/engine teardown. Durable file/session/event
    # state above is the only handoff channel to the next process.
    os._exit(HARD_EXIT_CODE)


def _resume(runtime: Path) -> None:
    state = _read_state(runtime)
    sid = str(state["session_id"])
    engine = _engine(runtime)
    if not engine.session.exists(sid):
        raise RuntimeError("original session missing after hard process exit")
    result = engine.run(sid, RESUME_PROMPT)
    state["resume"] = _run_facts(result)
    _write_state(runtime, state)


def _tool_names(run: dict[str, Any]) -> list[str]:
    return [str(item.get("name") or "") for item in run.get("tool_calls", [])]


def _path_from_call(call: dict[str, Any]) -> str:
    args = call.get("arguments") or {}
    return str(args.get("path") or "") if isinstance(args, dict) else ""


def _versioned_write_contract(calls: list[dict[str, Any]]) -> bool:
    """Observe whether each edit follows a prior snapshot read and carries a version ref."""
    snapshot_reads: dict[str, int] = {}
    saw_edit = False
    for call in calls:
        name = str(call.get("name") or "")
        args = call.get("arguments") or {}
        if not isinstance(args, dict):
            continue
        path = str(args.get("path") or "")
        if name == "read_file" and path and args.get("snapshot") is True:
            snapshot_reads[path] = snapshot_reads.get(path, 0) + 1
            continue
        if name != "edit_file":
            continue
        saw_edit = True
        ref = str(args.get("expected_snapshot_ref") or "")
        if not path or not ref.startswith("artifact://v1/"):
            return False
        if snapshot_reads.get(path, 0) <= 0:
            return False
        snapshot_reads[path] -= 1
    return saw_edit


def _evaluate(runtime: Path) -> dict[str, Any]:
    state = _read_state(runtime)
    workspace = runtime / "workspace"
    files = {
        f"item{idx}.txt": (workspace / f"item{idx}.txt").read_text(encoding="utf-8")
        for idx in range(1, 7)
    }
    initial = dict(state.get("initial") or {})
    resume = dict(state.get("resume") or {})
    initial_calls = list(initial.get("tool_calls") or [])
    resume_calls = list(resume.get("tool_calls") or [])

    final_files_ok = all(
        "STATUS: reviewed" in text
        and text.count(AI_MARKER) == 1
        and f"KEEP: keep-{idx}" in text
        for idx, text in enumerate(files.values(), start=1)
    )
    human_note_preserved = HUMAN_NOTE in files["item2.txt"]
    stale_not_landed = "STALE: must-not-land" not in files["item1.txt"]

    initial_edit_paths = [
        _path_from_call(call) for call in initial_calls if call.get("name") == "edit_file"
    ]
    resume_edit_paths = [
        _path_from_call(call) for call in resume_calls if call.get("name") == "edit_file"
    ]
    initial_scope_ok = set(initial_edit_paths) <= {"item1.txt", "item2.txt"} and {
        "item1.txt",
        "item2.txt",
    }.issubset(set(initial_edit_paths))
    no_repeat_completed_writes = not any(
        path in {"item1.txt", "item2.txt"} for path in resume_edit_paths
    )
    completed_remaining = all(
        f"item{idx}.txt" in resume_edit_paths for idx in range(3, 7)
    )

    resume_names = _tool_names(resume)
    observed_human_change = any(
        call.get("name") == "search_records"
        and isinstance(call.get("arguments"), dict)
        and call["arguments"].get("kind") == "file_effect"
        for call in resume_calls
    ) or any(
        call.get("name") == "read_file" and _path_from_call(call) == "item2.txt"
        for call in resume_calls
    )

    engine = _engine(runtime)
    effects = engine.file_effect_query
    assert effects is not None
    page = effects.query(
        session_id=str(state["session_id"]), workspace_scope=str(workspace), limit=50
    )
    receipt_facts = [r.public_facts() for r in page.receipts]
    human_effect_present = any(
        r["origin"] == "authenticated_user"
        and r["path"] == "item2.txt"
        and r["effect_state"] == "observed_match"
        for r in receipt_facts
    )
    stale_rejection_present = any(
        r["origin"] == "authenticated_user"
        and r["path"] == "item1.txt"
        and r["effect_state"] == "not_applied"
        for r in receipt_facts
    )
    model_receipts = [r for r in receipt_facts if r["origin"] == "model_tool"]
    model_effect_receipts_complete = bool(model_receipts) and all(
        r["effect_state"] == "observed_match"
        and r["causation_proven"] is True
        and bool(r["artifact_ref"])
        for r in model_receipts
    )

    mandatory = {
        "final_files_ok": final_files_ok,
        "human_note_preserved": human_note_preserved,
        "stale_not_landed": stale_not_landed,
        "stale_conflict_observed": bool((state.get("human") or {}).get("stale_item1_conflict")),
        "initial_scope_ok": initial_scope_ok,
        "initial_versioned_write_contract": _versioned_write_contract(initial_calls),
        "completed_remaining": completed_remaining,
        "no_repeat_completed_writes": no_repeat_completed_writes,
        "human_effect_present": human_effect_present,
        "stale_rejection_present": stale_rejection_present,
        "model_effect_receipts_complete": model_effect_receipts_complete,
    }
    protocol_continuity = {
        "initial_versioned_write_contract": _versioned_write_contract(initial_calls),
        "resume_versioned_write_contract": _versioned_write_contract(resume_calls),
    }
    costs = {
        "initial": {
            "rounds": initial.get("rounds", 0),
            "tokens_in": initial.get("tokens_in", 0),
            "tokens_out": initial.get("tokens_out", 0),
            "tokens_cache_hit": initial.get("tokens_cache_hit", 0),
        },
        "resume": {
            "rounds": resume.get("rounds", 0),
            "tokens_in": resume.get("tokens_in", 0),
            "tokens_out": resume.get("tokens_out", 0),
            "tokens_cache_hit": resume.get("tokens_cache_hit", 0),
        },
    }
    return {
        "qualified": all(mandatory.values()),
        "qualification_model_ref": _settings(runtime).llm_model,
        "mandatory": mandatory,
        "human_change_awareness_observed": observed_human_change,
        "human_change_awareness_note": (
            "model explicitly queried file_effect or re-read item2 after restart"
            if observed_human_change
            else "final bytes may be correct, but explicit observation of the human edit was not proven"
        ),
        "protocol_continuity": protocol_continuity,
        "hard_process_exit_expected": HARD_EXIT_CODE,
        "initial_tool_names": _tool_names(initial),
        "resume_tool_names": resume_names,
        "initial_edit_paths": initial_edit_paths,
        "resume_edit_paths": resume_edit_paths,
        "costs": costs,
        "files": files,
        "receipts": receipt_facts,
        "initial_final_answer": initial.get("final_answer", ""),
        "resume_final_answer": resume.get("final_answer", ""),
        "model_used_initial": initial.get("model_used", ""),
        "model_used_resume": resume.get("model_used", ""),
    }


def _child(script: Path, mode: str, runtime: Path, expected: int = 0) -> None:
    proc = subprocess.run(
        [sys.executable, str(script), "--mode", mode, "--runtime", str(runtime)],
        cwd=str(script.parents[2]),
        env={**os.environ, "PYTHONPATH": "src", "LMS_DIRECT": "0", "LLM_TRUST_ENV": "0"},
        check=False,
    )
    if proc.returncode != expected:
        raise RuntimeError(f"stage {mode} exit={proc.returncode}, expected={expected}")


def _orchestrate(runtime: Path) -> int:
    script = Path(__file__).resolve()
    _child(script, "setup", runtime)
    _child(script, "initial", runtime)
    _child(script, "human-hard-exit", runtime, expected=HARD_EXIT_CODE)
    _child(script, "resume", runtime)
    report = _evaluate(runtime)
    (runtime / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["qualified"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime",
        type=Path,
        required=True,
        help="isolated qualification runtime directory (must not be a production data dir)",
    )
    parser.add_argument(
        "--mode",
        choices=("orchestrate", "setup", "initial", "human-hard-exit", "resume", "evaluate"),
        default="orchestrate",
    )
    args = parser.parse_args()
    runtime = args.runtime.expanduser().resolve()
    if args.mode == "setup":
        _setup(runtime)
        return 0
    if args.mode == "initial":
        _initial(runtime)
        return 0
    if args.mode == "human-hard-exit":
        _human_hard_exit(runtime)
        return HARD_EXIT_CODE  # unreachable by design
    if args.mode == "resume":
        _resume(runtime)
        return 0
    if args.mode == "evaluate":
        print(json.dumps(_evaluate(runtime), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return _orchestrate(runtime)


if __name__ == "__main__":
    raise SystemExit(main())
