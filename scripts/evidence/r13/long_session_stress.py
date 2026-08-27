from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
R13_ROOT = ROOT / "data/audit/evidence_r13"
SOURCE_DIR = R13_ROOT / "sources"
FROZEN_PATH = ROOT / "tests/fixtures/evidence_r13/frozen_v1.json"
BASE_PROVIDERS = ROOT / "data/providers.json"
MODEL = "deepseek/deepseek-v4-flash"
STRESS_BUDGET = 50_000
PORT = 8919
MODES = ("off", "enforce")
CODES = [
    "ALPINE-417",
    "QUILL-826",
    "MAPLE-359",
    "COBALT-704",
    "WILLOW-281",
    "FJORD-638",
    "BRIAR-952",
    "CANVAS-146",
    "MICA-573",
    "ORCHID-809",
]


def verify_frozen_pack() -> dict[str, Any]:
    if not FROZEN_PATH.exists():
        raise RuntimeError(f"R13 frozen lock missing: {FROZEN_PATH}")
    payload = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != "evidence-r13-frozen-v1":
        raise RuntimeError("R13 frozen lock schema mismatch")
    mismatches: list[str] = []
    for rel, expected in payload.get("artifacts", {}).items():
        path = ROOT / rel
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"
        if actual != expected:
            mismatches.append(f"{rel}: expected={expected} actual={actual}")
    if mismatches:
        raise RuntimeError("R13 frozen artifact mismatch: " + "; ".join(mismatches))
    current_sources = prepare_sources()
    if current_sources != payload.get("source_hashes"):
        raise RuntimeError("R13 source fixture hashes mismatch")
    return payload


def _source_rel(index: int) -> str:
    return f"data/audit/evidence_r13/sources/r13_source_{index:02d}.txt"


def prepare_sources() -> dict[str, str]:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for i, code in enumerate(CODES, 1):
        rows = [
            f"R13 file {i:02d} row {j:04d}: neutral long-session cache/compression material segment {j % 17:02d}."
            for j in range(360)
        ]
        rows.insert(177, f"R13-CODE-{i:02d}: {code}")
        text = "\n".join(rows) + "\n"
        path = ROOT / _source_rel(i)
        path.write_text(text, encoding="utf-8")
        hashes[_source_rel(i)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def scenario() -> list[dict[str, Any]]:
    def new(i: int) -> str:
        return (
            f"请使用 read_file 的 full=true 读取 `{_source_rel(i)}`，找出精确字段 "
            f"`R13-CODE-{i:02d}` 的值并汇报。"
        )

    return [
        {"turn": 1, "message": new(1), "expect": [CODES[0]]},
        {"turn": 2, "message": new(2), "expect": [CODES[1]]},
        {
            "turn": 3,
            "message": new(3) + " 同时给出第1轮文件的 R13-CODE-01 值。",
            "expect": [CODES[2], CODES[0]],
        },
        {"turn": 4, "message": new(4), "expect": [CODES[3]]},
        {
            "turn": 5,
            "message": new(5) + " 同时给出第2轮文件的 R13-CODE-02 值。",
            "expect": [CODES[4], CODES[1]],
        },
        {
            "turn": 6,
            "message": new(6) + " 同时给出第1轮文件的 R13-CODE-01 值。",
            "expect": [CODES[5], CODES[0]],
        },
        {"turn": 7, "message": new(7), "expect": [CODES[6]]},
        {
            "turn": 8,
            "message": new(8) + " 同时给出第3轮文件的 R13-CODE-03 值。",
            "expect": [CODES[7], CODES[2]],
        },
        {
            "turn": 9,
            "message": new(9) + " 同时给出第1轮文件的 R13-CODE-01 值。",
            "expect": [CODES[8], CODES[0]],
        },
        {
            "turn": 10,
            "message": new(10) + " 同时给出第5轮文件的 R13-CODE-05 值。",
            "expect": [CODES[9], CODES[4]],
        },
        {
            "turn": 11,
            "message": "请给出此前第1、4、7、10个文件各自的 R13-CODE 值；需要工具时自行决定。",
            "expect": [CODES[0], CODES[3], CODES[6], CODES[9]],
        },
        {
            "turn": 12,
            "message": "最终核对：请按 01→10 顺序列出本会话十个 R13-CODE 的值。",
            "expect": list(CODES),
        },
    ]


def _runtime(mode: str) -> Path:
    return R13_ROOT / "runtime" / mode


def prepare_runtime(mode: str) -> Path:
    root = _runtime(mode)
    if root.exists():
        import shutil

        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    providers = json.loads(BASE_PROVIDERS.read_text(encoding="utf-8"))
    providers["deepseek"]["history_budget_chars"] = STRESS_BUDGET
    (root / "providers.json").write_text(
        json.dumps(providers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return root


def _url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def _get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def _post_chat(port: int, session_id: str | None, message: str, *, new: bool) -> dict[str, Any]:
    body: dict[str, Any] = {"message": message, "model": MODEL}
    if new:
        body["new_session"] = True
    elif session_id:
        body["session_id"] = session_id
    request = urllib.request.Request(
        _url(port, "/api/v1/chat"),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read())


def start_server(mode: str, port: int) -> tuple[subprocess.Popen[bytes], Any]:
    runtime = prepare_runtime(mode)
    log_path = R13_ROOT / f"web_{mode}.log"
    log = log_path.open("wb")
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT / "src"),
            "WEB_HOST": "127.0.0.1",
            "WEB_PORT": str(port),
            "DATA_DIR": str(runtime),
            "LFL_DATA_DIR": str(runtime),
            "EVIDENCE_MODE": mode,
            "MODEL_PROVIDERS": "",
        }
    )
    proc = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "llm_loop.web"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    for _ in range(60):
        if proc.poll() is not None:
            log.flush()
            raise RuntimeError(f"R13 {mode} web exited early rc={proc.returncode}; see {log_path}")
        try:
            health = _get_json(_url(port, "/health"), timeout=1.0)
            if health.get("status") == "ok":
                return proc, log
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"R13 {mode} web did not become healthy; see {log_path}")


def stop_server(proc: subprocess.Popen[bytes], log: Any) -> None:
    try:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
    finally:
        log.close()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _parse_call(raw: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    call_id = str(raw.get("id") or "")
    fn = raw.get("function") or {}
    name = str(fn.get("name") or raw.get("name") or "")
    args_raw = fn.get("arguments", raw.get("arguments", {}))
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw or "{}")
        except ValueError:
            args = {}
    else:
        args = args_raw if isinstance(args_raw, dict) else {}
    return name, args, call_id


def analyze(mode: str, session_id: str, turn_results: list[dict[str, Any]]) -> dict[str, Any]:
    runtime = _runtime(mode)
    events = read_jsonl(runtime / "event_logs" / f"{session_id}.jsonl")
    meta: list[tuple[int, dict[str, Any]]] = []
    usage: list[tuple[int, dict[str, Any]]] = []
    windows: list[tuple[int, dict[str, Any]]] = []
    compressions: list[tuple[int, dict[str, Any]]] = []
    call_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    declared_reads: list[dict[str, Any]] = []
    recovery_calls = 0
    tool_non_success_count = 0
    unresolved_run_errors = 0
    physical_reads: list[str] = []
    evidence_reuses: list[str] = []

    for event in events:
        seq = int(event.get("seq") or 0)
        typ = event.get("type")
        payload = event.get("payload") or {}
        if typ == "request.meta":
            meta.append((seq, payload))
        elif typ == "request.usage":
            usage.append((seq, payload))
        elif typ == "cache.window":
            windows.append((seq, payload))
        elif typ == "context.compressed":
            compressions.append((seq, payload))
        elif typ == "run.end":
            if str(payload.get("reason") or "") != "completed":
                unresolved_run_errors += 1
        elif typ == "message.appended":
            role = payload.get("role")
            if role == "assistant":
                for raw in payload.get("tool_calls") or []:
                    if not isinstance(raw, dict):
                        continue
                    name, args, call_id = _parse_call(raw)
                    if call_id:
                        call_by_id[call_id] = (name, args)
                    if name == "read_file":
                        declared_reads.append({"seq": seq, "id": call_id, "args": args})
                    if name in {
                        "list_evidence",
                        "search_evidence",
                        "read_evidence",
                        "search_archive",
                    }:
                        recovery_calls += 1
            elif role == "tool":
                status = str(payload.get("status") or "")
                if status and status not in {"success"}:
                    tool_non_success_count += 1
                if payload.get("tool_name") == "read_file":
                    call_id = str(payload.get("tool_call_id") or "")
                    _, args = call_by_id.get(call_id, ("read_file", {}))
                    path = str(args.get("path") or "")
                    md = payload.get("metadata") or {}
                    performed = md.get("source_execution_performed")
                    if mode == "enforce" and performed is False:
                        evidence_reuses.append(path)
                    else:
                        physical_reads.append(path)

    def repeats(paths: list[str]) -> int:
        seen: set[str] = set()
        out = 0
        for path in paths:
            if path in seen:
                out += 1
            else:
                seen.add(path)
        return out

    declared_paths = [str(row["args"].get("path") or "") for row in declared_reads]
    tools_values = sorted({int(p.get("tools_count") or 0) for _, p in meta})
    budget_values = sorted({int(p.get("budget") or 0) for _, p in meta})
    models = sorted({str(p.get("model") or "") for _, p in meta})
    hit_ratios = [float(p.get("hit_ratio") or 0.0) for _, p in windows]
    postwarm = hit_ratios[2:]
    median_hit = statistics.median(postwarm) if postwarm else 0.0

    # Boundary backward jump is suspicious only if no compression event occurred since prior cache window.
    backjumps = 0
    unexplained_backjumps = 0
    prev_seq: int | None = None
    prev_boundary: int | None = None
    compression_seqs = [seq for seq, _ in compressions]
    for seq, payload in windows:
        boundary = payload.get("boundary_msg_index")
        if not isinstance(boundary, int):
            prev_seq, prev_boundary = seq, None
            continue
        if prev_boundary is not None and boundary < prev_boundary:
            backjumps += 1
            if prev_seq is not None and not any(prev_seq < cseq < seq for cseq in compression_seqs):
                unexplained_backjumps += 1
        prev_seq, prev_boundary = seq, boundary

    # Compression counts between request.meta snapshots + streak of intervals with compression.
    compression_between: list[int] = []
    if meta:
        prev = 0
        for seq, _ in meta:
            compression_between.append(sum(prev < cseq < seq for cseq in compression_seqs))
            prev = seq
    max_between = max(compression_between, default=0)
    max_streak = 0
    cur = 0
    for count in compression_between:
        if count > 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0

    low_cliff_count = 0
    cur = 0
    for rate in hit_ratios[2:]:
        if rate < 0.50:
            cur += 1
            if cur == 3:
                low_cliff_count += 1
        else:
            cur = 0

    turn_ok = [bool(row.get("correct")) for row in turn_results]
    final_all = bool(
        turn_results
        and all(code in str(turn_results[-1].get("final_answer") or "") for code in CODES)
    )
    return {
        "mode": mode,
        "session_id": session_id,
        "turn_count": len(turn_results),
        "turn_correct": sum(turn_ok),
        "final_all_codes": final_all,
        "api_requests": len(meta),
        "tools_count_values": tools_values,
        "budget_values": budget_values,
        "models": models,
        "history_chars": [int(p.get("history_chars") or 0) for _, p in meta],
        "usage": [p for _, p in usage],
        "cache_windows": [p for _, p in windows],
        "cache_hit_ratios": hit_ratios,
        "postwarm_median_hit_ratio": median_hit,
        "prefix_cliff_count": low_cliff_count,
        "cache_boundary_backjumps": backjumps,
        "unexplained_cache_boundary_backjumps": unexplained_backjumps,
        "context_compressed_count": len(compressions),
        "compression_between_requests": compression_between,
        "max_compression_events_between_requests": max_between,
        "max_compression_streak": max_streak,
        "declared_read_file_count": len(declared_paths),
        "declared_repeated_source_paths": repeats(declared_paths),
        "physical_read_file_count": len(physical_reads),
        "physical_repeated_source_paths": repeats(physical_reads),
        "evidence_reuse_count": len(evidence_reuses),
        "recovery_tool_declarations": recovery_calls,
        "tool_non_success_count": tool_non_success_count,
        "unresolved_run_errors": unresolved_run_errors,
        "turn_results": turn_results,
    }


def per_mode_gates(report: dict[str, Any]) -> dict[str, bool]:
    ratios = report["cache_hit_ratios"]
    return {
        "turns_12": report["turn_count"] == 12,
        "correct_ge_11_12": report["turn_correct"] >= 11,
        "final_all_codes": bool(report["final_all_codes"]),
        "one_model": report["models"] == [MODEL],
        "stable_tools_count": len(report["tools_count_values"]) == 1,
        "stable_budget_50k": report["budget_values"] == [STRESS_BUDGET],
        "no_unresolved_run_error": report["unresolved_run_errors"] == 0,
        "compression_streak_lt_5": report["max_compression_streak"] < 5,
        "compression_between_le_3": report["max_compression_events_between_requests"] <= 3,
        "no_persistent_prefix_cliff": report["prefix_cliff_count"] == 0,
        "median_postwarm_hit_ge_70": report["postwarm_median_hit_ratio"] >= 0.70
        if len(ratios) > 2
        else False,
    }


def paired_gates(off: dict[str, Any], enforce: dict[str, Any]) -> dict[str, bool]:
    return {
        "enforce_physical_repeats_le_off": enforce["physical_repeated_source_paths"]
        <= off["physical_repeated_source_paths"],
        "enforce_physical_reads_bounded": enforce["physical_read_file_count"]
        <= off["physical_read_file_count"] + 10,
        "enforce_compression_count_le_off": enforce["context_compressed_count"]
        <= off["context_compressed_count"],
        "enforce_compression_streak_le_off_plus_1": enforce["max_compression_streak"]
        <= off["max_compression_streak"] + 1,
        "enforce_cache_median_not_worse_10pt": enforce["postwarm_median_hit_ratio"] + 0.10
        >= off["postwarm_median_hit_ratio"],
        "enforce_prefix_cliffs_le_off": enforce["prefix_cliff_count"] <= off["prefix_cliff_count"],
    }


def run_mode(mode: str, port: int = PORT) -> dict[str, Any]:
    proc, log = start_server(mode, port)
    try:
        warm = _post_chat(port, None, "R13 warmup：只回答 WARMUP_OK。", new=True)
        if "WARMUP_OK" not in str(warm.get("final_answer") or ""):
            raise RuntimeError(f"warmup failed for {mode}: {warm}")
        session_id: str | None = None
        turn_results: list[dict[str, Any]] = []
        for item in scenario():
            response = _post_chat(port, session_id, item["message"], new=session_id is None)
            session_id = str(response["session_id"])
            answer = str(response.get("final_answer") or "")
            correct = all(token in answer for token in item["expect"])
            turn_results.append(
                {
                    "turn": item["turn"],
                    "expect": item["expect"],
                    "correct": correct,
                    "final_answer": answer,
                }
            )
            print(
                mode,
                "turn",
                item["turn"],
                "correct=",
                correct,
                "answer_head=",
                repr(answer[:100]),
                flush=True,
            )
        assert session_id is not None
        report = analyze(mode, session_id, turn_results)
        report["gates"] = per_mode_gates(report)
        out = R13_ROOT / f"report_{mode}_v1.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in [
                        "mode",
                        "session_id",
                        "turn_correct",
                        "api_requests",
                        "tools_count_values",
                        "budget_values",
                        "postwarm_median_hit_ratio",
                        "prefix_cliff_count",
                        "context_compressed_count",
                        "max_compression_streak",
                        "max_compression_events_between_requests",
                        "unexplained_cache_boundary_backjumps",
                        "declared_read_file_count",
                        "physical_read_file_count",
                        "physical_repeated_source_paths",
                        "evidence_reuse_count",
                        "recovery_tool_declarations",
                    ]
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("gates", report["gates"])
        return report
    finally:
        stop_server(proc, log)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--score", action="store_true")
    args = parser.parse_args()
    hashes = prepare_sources()
    (R13_ROOT / "source_hashes_v1.json").write_text(
        json.dumps(hashes, indent=2) + "\n", encoding="utf-8"
    )
    if args.prepare:
        print(
            json.dumps(
                {"source_hashes": hashes, "scenario": scenario()}, ensure_ascii=False, indent=2
            )
        )
        return 0
    if args.mode:
        verify_frozen_pack()
        report = run_mode(args.mode)
        return 0 if all(report["gates"].values()) else 1
    if args.score:
        off = json.loads((R13_ROOT / "report_off_v1.json").read_text())
        enforce = json.loads((R13_ROOT / "report_enforce_v1.json").read_text())
        paired = paired_gates(off, enforce)
        payload = {
            "schema": "evidence-r13-score-v1",
            "status": "PASS"
            if all(off["gates"].values())
            and all(enforce["gates"].values())
            and all(paired.values())
            else "FAIL",
            "off_gates": off["gates"],
            "enforce_gates": enforce["gates"],
            "paired_gates": paired,
        }
        (R13_ROOT / "score_v1.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "PASS" else 1
    parser.error("select --prepare, --mode or --score")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
