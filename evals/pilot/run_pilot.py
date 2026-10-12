#!/usr/bin/env python3
"""Agent 评测 pilot 运行器。

适配器：lfl（python -m llm_loop.cli） / da（deepagents，同一 8901 Ornith 模型）。
用法：
  python3 run_pilot.py --agents lfl,da --tasks t01,t02 --runs 1 --workdir /tmp/agentpilot
  python3 run_pilot.py --agents lfl --tasks t12 --runs 1 --interrupt   # 中断续做协议
结果：workdir/results.jsonl + summary.md
公平性：两个 agent 使用同一模型（cognilocal/ornith-1.5-35b-a3b-mlx @ 8901）、
        同一任务工作区快照、同一 verifier、同一 wall-clock 预算（task.timeout_s）。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import telemetry as _tl

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import tasks  # noqa: E402
from tasks import TASKS  # noqa: E402

LFL_MODEL = "cognilocal/ornith-1.5-35b-a3b-mlx"
DA_MODEL_ID = "ornith-ai/Ornith-1.5-35B-A3B-MLX"
DA_BASE_URL = "http://127.0.0.1:8901/v1"

DA_ADAPTER = r'''
import json, os, subprocess, sys, time
from typing import Optional
from pathlib import Path

def make_tools():
    from langchain_core.tools import tool

    @tool
    def read_file(path: str, offset: int = 1, limit: int = 2000) -> str:
        """Read a text file relative to the workspace. offset is 1-based line number; limit caps lines."""
        p = Path(os.path.realpath(path))
        if not p.is_file(): return f"ERROR: not a file: {path}"
        try:
            lines = p.read_text(errors="replace").splitlines()
        except Exception as e:
            return f"ERROR: {e}"
        seg = lines[offset-1: offset-1+limit]
        return "".join(ln + "\n" for ln in seg) + (f"[truncated: showing {len(seg)}/{len(lines)} lines]" if offset-1+limit < len(lines) else "")

    @tool
    def write_file(path: str, content: str) -> str:
        """Write (overwrite) a text file relative to the workspace."""
        try:
            Path(path).write_text(content)
            return f"wrote {len(content)} chars to {path}"
        except Exception as e:
            return f"ERROR: {e}"

    @tool
    def list_dir(path: str = ".") -> str:
        """List directory entries (name + type), one per line."""
        try:
            out = []
            for e in sorted(Path(path).iterdir()):
                out.append(("d " if e.is_dir() else "f ") + e.name)
            return "\n".join(out) or "(empty)"
        except Exception as e:
            return f"ERROR: {e}"

    @tool
    def run_command(command: str, timeout_s: int = 60) -> str:
        """Run a shell command in the workspace with a timeout. Returns exit code, stdout, stderr (each capped at 4000 chars)."""
        try:
            r = subprocess.run(["/bin/zsh", "-c", command], capture_output=True, text=True, timeout=timeout_s)
            def cap(s): return s if len(s) <= 4000 else s[:4000] + f"\n[...truncated {len(s)-4000} chars]"
            return json.dumps({"exit": r.returncode, "stdout": cap(r.stdout), "stderr": cap(r.stderr)})
        except subprocess.TimeoutExpired:
            return json.dumps({"exit": -1, "stdout": "", "stderr": f"TIMEOUT after {timeout_s}s"})
        except Exception as e:
            return json.dumps({"exit": -1, "stdout": "", "stderr": f"ERROR: {e}"})

    return [read_file, write_file, list_dir, run_command]

def main():
    prompt = sys.argv[1]
    from langchain_openai import ChatOpenAI
    from deepagents import create_deep_agent
    llm = ChatOpenAI(model=MODEL_ID, base_url=BASE_URL, api_key="local-eval", temperature=0.2, max_retries=2)
    agent = create_deep_agent(tools=make_tools(), model=llm,
        system_prompt="You are a coding agent in a sandbox workspace. Use tools; never fabricate file contents. Finish the task, then reply DONE.")
    cfg = {"recursion_limit": 80}
    t0 = time.time()
    state = agent.invoke({"messages": [("user", prompt)]}, config=cfg)
    msgs = state["messages"]
    # --- telemetry v0.2：tool_call_id 精确配对（declared tool_calls → ToolMessage 结果）---
    # 口径统一：rounds = AIMessage 数（不再用 len(msgs) 混入 tool messages）；
    #           tool_calls = declared 调用数；ok 由结果消息判定并附 result 摘要
    #           （≤2000 字符 + result_len/result_truncated 截断显式标记，F08 修复）。
    events = {"t0": "", "calls": [], "turns": [], "source": "da:adapter-stdout"}
    turn = 0
    for m in msgs:
        mt = getattr(m, "type", "")
        if mt == "ai":
            turn += 1
            u = getattr(m, "usage_metadata", None) or {}
            det = u.get("input_token_details") or {}
            cached = det.get("cache_read")
            if cached is None:
                cached = det.get("cached")  # LangChain 版本键名兼容
            events["turns"].append({"tokens_in": u.get("input_tokens"), "cached": cached,
                                    "tokens_out": u.get("output_tokens")})
            for tc in getattr(m, "tool_calls", None) or []:
                events["calls"].append({"name": tc.get("name"), "args": tc.get("args"),
                                        "ok": None, "result": None, "turn": turn,
                                        "call_id": tc.get("id")})  # F08：保留机械身份，不再事后移除
        elif mt == "tool":
            body = str(getattr(m, "content", ""))
            tcid = getattr(m, "tool_call_id", None)
            for c in events["calls"]:
                if c["ok"] is None and ((tcid and c.get("call_id") == tcid) or not tcid):
                    c["ok"] = not (body.startswith("ERROR:") or '"exit": -1' in body[:80])
                    c["result"] = body[:2000]
                    c["result_len"] = len(body)
                    c["result_truncated"] = len(body) > 2000
                    break
    # F08 修复：不再移除 call_id（raw 层保留机械身份；scorer 不消费）
    n_tool = len(events["calls"])
    n_rounds = sum(1 for m in msgs if getattr(m, "type", "") == "ai")
    last = ""
    for m in reversed(msgs):
        if getattr(m, "type", "") == "ai" and getattr(m, "content", ""):
            last = m.content if isinstance(m.content, str) else str(m.content); break
    print(json.dumps({"rounds": n_rounds, "tool_calls": n_tool, "final": last[:2000], "telemetry": events}))

if __name__ == "__main__":
    main()
'''

def sh(cmd: str, cwd: Path, timeout: int = 30) -> None:
    r = subprocess.run(["/bin/zsh", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"setup failed: {r.stderr[:500]}")

def verify(task: dict, ws: Path) -> tuple[bool, str]:
    try:
        r = subprocess.run([sys.executable, "-c", task["verify"]], cwd=ws, capture_output=True, text=True, timeout=60)
        return r.returncode == 0, (r.stderr[-300:] if r.returncode else "")
    except subprocess.TimeoutExpired:
        # verifier 挂起=测量设施故障，不是任务失败（§18.1 任务 verifier 健壮性）
        return False, "VERIFIER-TIMEOUT-60s"


def _prepare_effect_probe(task: dict, ws: Path, base_env: dict[str, str]) -> dict[str, str]:
    """Install a task-scoped process-exit observer without changing task source.

    The shim records only mechanical child-process facts. It never parses stdout/stderr,
    never changes the child exit code, and is enabled only by an explicit task contract.
    """
    probe = task.get("effect_probe")
    env = dict(base_env)
    if not probe:
        return env
    if probe.get("kind") != "process_exit":
        raise RuntimeError(f"unsupported effect_probe kind: {probe.get('kind')!r}")
    target = str(probe.get("target_basename") or "")
    check_id = str(probe.get("check_id") or "")
    effect_dir = ws.parent / ".agentpilot-effect-probes" / ws.name
    shim_dir = effect_dir / "bin"
    # Re-entry safe: never resolve the shim itself as the real interpreter.
    clean_path = os.pathsep.join(
        entry for entry in env.get("PATH", "").split(os.pathsep)
        if entry and Path(entry).resolve() != shim_dir.resolve()
    )
    real_python3 = shutil.which("python3", path=clean_path)
    if not real_python3:
        raise RuntimeError("effect_probe requires python3 in PATH")
    shim_dir.mkdir(parents=True, exist_ok=True)
    log_path = effect_dir / "events.jsonl"
    shim = shim_dir / "python3"
    qreal = shlex.quote(real_python3)
    qlog = shlex.quote(str(log_path))
    qtarget = shlex.quote(target)
    qcheck = shlex.quote(check_id)
    shim.write_text(f'''#!/bin/zsh
REAL={qreal}
LOG={qlog}
TARGET={qtarget}
CHECK_ID={qcheck}
"$REAL" "$@"
rc=$?
matched=0
for arg in "$@"; do
  if [[ "${{arg:t}}" == "$TARGET" ]]; then
    matched=1
    break
  fi
done
if [[ "$matched" == "1" ]]; then
  mkdir -p "${{LOG:h}}"
  if [[ -f "$LOG" ]]; then
    n=$(wc -l < "$LOG" | tr -d ' ')
  else
    n=0
  fi
  attempt=$((n + 1))
  printf '{{"schema":"agentpilot-task-effect/v1","check_id":"%s","target":"%s","scope":"workspace","attempt":%d,"exit_code":%d}}\n' "$CHECK_ID" "$TARGET" "$attempt" "$rc" >> "$LOG"
fi
exit "$rc"
''')
    shim.chmod(0o755)
    env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
    return env


def _collect_task_effects(task: dict, ws: Path) -> tuple[list[dict], str]:
    """Read and validate the closed task-effect receipt, if configured."""
    probe = task.get("effect_probe")
    if not probe:
        return [], "not_configured"
    log_path = ws.parent / ".agentpilot-effect-probes" / ws.name / "events.jsonl"
    if not log_path.exists():
        return [], "missing"
    allowed = {"schema", "check_id", "target", "scope", "attempt", "exit_code"}
    effects: list[dict] = []
    try:
        for idx, line in enumerate(log_path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or set(row) != allowed:
                return [], "invalid_schema"
            if row.get("schema") != "agentpilot-task-effect/v1":
                return [], "invalid_schema"
            if row.get("check_id") != probe.get("check_id"):
                return [], "invalid_check_id"
            if row.get("target") != probe.get("target_basename") or row.get("scope") != "workspace":
                return [], "invalid_target_scope"
            if row.get("attempt") != idx or not isinstance(row.get("exit_code"), int):
                return [], "invalid_sequence"
            effects.append(row)
    except (OSError, json.JSONDecodeError):
        return [], "invalid_json"
    return effects, "ok"

def _lfl_env(ws: Path) -> dict:
    """会话/记忆存储隔离：每 run 独立 DATA_DIR（主路径 load_settings 读 DATA_DIR env）。
    v0 原始 33 条 LFL run 未隔离（共享仓库 data/）；本修复仅影响 t12 复测与后续正式矩阵，
    manifest 已记录该差异。
    2026-09-12 复测教训：隔离后的空 DATA_DIR 缺 providers.json → '未知 provider: cognilocal'，
    phase1 亦被回退到默认 contract（glm/glm-5.3 400）。providers.py 加载优先级第 3 位恰为
    {data_dir}/providers.json（tracked seed），故每 ws 首次调用时从仓库 data/ 复制一份；
    会话/记忆仍写隔离目录，不影响隔离目的。"""
    env = dict(os.environ)
    dd = ws / ".lfldata"
    dd.mkdir(exist_ok=True)
    src = REPO / "data" / "providers.json"
    dst = dd / "providers.json"
    if src.exists() and not dst.exists():
        dst.write_bytes(src.read_bytes())
    env["DATA_DIR"] = str(dd)
    return env

def _lfl_full_sid(ws: Path, prefix8: str) -> str:
    """CLI 输出仅显示 session id 前 8 位；从隔离 store 的 sessions/<identity-slug>/<sid>.json
    反查完整 id（rglob 兼容 identity 子目录；同前缀多条时取最新 mtime）。"""
    if not prefix8:
        return ""
    store = ws / ".lfldata" / "sessions"
    if not store.is_dir():
        return ""
    m = sorted(store.rglob(prefix8 + "*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return m[0].stem if m else ""

def _lfl_newest_session_sid(ws: Path) -> str:
    """2026-09-12 复测追加：SIGKILL 命中 mid-turn 时 CLI 从未打印 [会话 …] 行，
    stdout 无 sid——这才是 v0 phase1_sid 恒空的最深根因（800 字符截断只是次生）。
    kill 后、resume 前调用：隔离 store 内此刻仅有 phase1 的会话文件（resume 尚未启动），
    取最新 mtime 的 session json 即 phase1 sid。跳过 .identity 元数据目录。"""
    store = ws / ".lfldata" / "sessions"
    if not store.is_dir():
        return ""
    m = sorted((p for p in store.rglob("*.json") if ".identity" not in p.parts),
               key=lambda p: p.stat().st_mtime, reverse=True)
    return m[0].stem if m else ""

def run_lfl(task: dict, ws: Path, deadline_s: int) -> dict:
    env = _prepare_effect_probe(task, ws, _lfl_env(ws))
    cmd = [str(REPO / ".venv/bin/python"), "-m", "llm_loop.cli", "--model", LFL_MODEL, task["prompt"]]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=deadline_s)
        out, rc, dur = r.stdout, r.returncode, round(time.time() - t0, 1)
        stats = [ln for ln in out.splitlines() if ln.startswith("[会话")]
        sid8 = stats[0].split("[会话 ")[1][:8] if stats else ""
        sid_full = _lfl_full_sid(ws, sid8)
        fc, fev = _tl.fcr_lfl(ws, sid_full or sid8)   # (raw, events)：events 随结果落盘供 scorer 复算
        return {"ok_run": rc == 0, "dur": dur, "stats": stats[0] if stats else "", "session": sid_full or sid8,
                "first_call": fc, "fcr_events": fev,
                "stdout_tail": out[-1500:], "stderr_tail": r.stderr[-500:]}
    except subprocess.TimeoutExpired:
        return {"ok_run": False, "dur": deadline_s, "stats": "", "session": "",
                "first_call": None, "fcr_events": None, "stdout_tail": "HARNESS-TIMEOUT", "stderr_tail": ""}

def run_da(task: dict, ws: Path, deadline_s: int) -> dict:
    adapter = ws / "_da_adapter.py"
    adapter.write_text(DA_ADAPTER.replace("MODEL_ID", repr(DA_MODEL_ID)).replace("BASE_URL", repr(DA_BASE_URL)))
    cmd = [str(HERE / ".venv-da/bin/python"), str(adapter), task["prompt"]]
    t0 = time.time()
    try:
        env = _prepare_effect_probe(task, ws, dict(os.environ))
        r = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=deadline_s)
        out, rc, dur = r.stdout, r.returncode, round(time.time() - t0, 1)
        meta = {}
        for line in out.splitlines():
            try:
                j = json.loads(line)
                if isinstance(j, dict) and "tool_calls" in j:
                    meta = j
                    break
            except Exception:
                pass
        tel = meta.get("telemetry") or {}
        fc, fev = _tl.fcr_da(tel)
        return {"ok_run": rc == 0, "dur": dur, "stats": f'rounds={meta.get("rounds")} tools={meta.get("tool_calls")}',
                "session": "", "first_call": fc, "fcr_events": fev,
                "stdout_tail": (meta.get("final", "") + "\n--\n" + out)[-1500:], "stderr_tail": r.stderr[-500:]}
    except subprocess.TimeoutExpired:
        return {"ok_run": False, "dur": deadline_s, "stats": "", "session": "", "first_call": None, "fcr_events": None,
                "stdout_tail": "HARNESS-TIMEOUT", "stderr_tail": ""}

# ---------- cline adapter（provider/model/base-url 由 runner 每 run 隔离固定，不依赖 ~/.cline） ----------
CLINE_MODEL = "ornith-ai/Ornith-1.5-35B-A3B-MLX"  # 与 LFL_MODEL/DA_MODEL_ID 同一 8901 物理模型（唯一 ornith 目录）

def _cline_paths(ws: Path) -> tuple[Path, Path]:
    root = ws.parent
    return root / ".cline-configs" / ws.name, root / ".cline-data" / ws.name

def _ensure_cline_config(ws: Path) -> tuple[bool, str]:
    """Pin Cline's OpenAI-compatible endpoint mechanically for this run.

    Cline 3.0.61 otherwise inherits mutable user-global provider/model settings; a
    real smoke proved that drift can silently select gpt-4o/OpenAI instead of 8901.
    The credential is a non-secret local dummy bearer accepted by the local server.
    """
    cfg, _data_dir = _cline_paths(ws)
    cfg.mkdir(parents=True, exist_ok=True)
    marker = cfg / ".agentpilot-v1.json"
    expected = {"provider": "openai-compatible", "model": CLINE_MODEL, "base_url": DA_BASE_URL}
    if marker.exists():
        try:
            if json.loads(marker.read_text()) == expected:
                return True, ""
        except Exception:
            pass
    try:
        r = subprocess.run(
            ["cline", "--config", str(cfg), "auth", "-p", "openai-compatible",
             "-k", "local-eval", "-m", CLINE_MODEL, "-b", DA_BASE_URL],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:  # noqa: BLE001 - adapter setup failure is surfaced as infra fact
        return False, f"CLINE-CONFIG-FAILED: {type(e).__name__}: {e}"
    if r.returncode != 0:
        return False, f"CLINE-CONFIG-FAILED rc={r.returncode}: {(r.stderr or r.stdout)[-500:]}"
    marker.write_text(json.dumps(expected, sort_keys=True))
    return True, ""

def _cline_cmd(prompt: str, ws: Path, deadline_s: int, session_id: str = "") -> list:
    cfg, _data_dir = _cline_paths(ws)
    cmd = ["cline", "--config", str(cfg),
           "-P", "openai-compatible", "-k", "local-eval", "-m", CLINE_MODEL,
           "--auto-approve", "true", "--json",
           "-c", str(ws.resolve()), "-t", str(deadline_s)]
    if session_id:
        cmd += ["--id", session_id]
    cmd.append(prompt)
    return cmd

def _cline_parse(out: str) -> dict:
    taskid, meta = "", {}
    for line in out.splitlines():
        try:
            j = json.loads(line)
        except Exception:
            continue
        if not isinstance(j, dict):
            continue
        ev = j.get("event") if isinstance(j.get("event"), dict) else {}
        for tid in (j.get("taskId"), ev.get("taskId"), ev.get("task_id")):
            if isinstance(tid, str) and tid.startswith("conv_"):
                taskid = tid
        rr = j if j.get("type") == "run_result" else (ev if ev.get("type") == "run_result" else None)
        if rr:
            meta = {"finish": rr.get("finishReason"), "iters": rr.get("iterations"),
                    "dur_ms": rr.get("durationMs"), "model": (rr.get("model") or {}).get("id", "")}
    return {"taskid": taskid, "meta": meta}

def run_cline(task: dict, ws: Path, deadline_s: int, session_id: str = "") -> dict:
    t0 = time.time()
    configured, config_err = _ensure_cline_config(ws)
    if not configured:
        return {"ok_run": False, "dur": round(time.time() - t0, 1), "stats": "cline-config-failed",
                "session": "", "first_call": None, "fcr_events": None,
                "stdout_tail": "", "stderr_tail": config_err}
    try:
        env = _prepare_effect_probe(task, ws, dict(os.environ))
        r = subprocess.run(_cline_cmd(task["prompt"], ws, deadline_s, session_id),
                           cwd=ws, env=env, capture_output=True, text=True, timeout=deadline_s + 60)
        out, rc, dur = r.stdout, r.returncode, round(time.time() - t0, 1)
        info = _cline_parse(out)
        meta = info["meta"]
        (ws / ".cline_stream.jsonl").write_text(out)   # full --json stream, for telemetry backtracking/auditing
        fc, fev = _tl.fcr_cline(out)
        return {"ok_run": rc == 0 and meta.get("finish") != "error",
                "dur": dur,
                "stats": f"iters={meta.get('iters')} finish={meta.get('finish')} model={meta.get('model')}",
                "session": info["taskid"],
                "first_call": fc, "fcr_events": fev,
                "stdout_tail": out[-1500:], "stderr_tail": r.stderr[-500:]}
    except subprocess.TimeoutExpired:
        return {"ok_run": False, "dur": deadline_s, "stats": "", "session": "", "first_call": None, "fcr_events": None,
                "stdout_tail": "HARNESS-TIMEOUT", "stderr_tail": ""}

ADAPTERS = {"lfl": run_lfl, "da": run_da, "cline": run_cline}

def with_ws(prompt: str, ws: Path) -> str:
    """公平性：两个 agent 的工具默认 cwd 语义不同（lfl=仓库根，da=进程cwd），
    统一在 prompt 中给出绝对工作目录。"""
    return f"工作目录（绝对路径）：{ws.resolve()}。所有文件读写与命令都应针对此目录下的文件（可用绝对路径）。任务：{prompt}"

def _merge_resume_result(rec: dict, resume_result: dict) -> None:
    """Merge one resume attempt without double-prefixing already-qualified semantics."""
    rec.update({
        f"resume_{k}": v
        for k, v in resume_result.items()
        if k != "resume_semantics"
    })
    if "resume_semantics" in resume_result:
        rec["resume_semantics"] = resume_result["resume_semantics"]


def run_one(agent: str, task: dict, run_idx: int, base: Path, interrupt: bool) -> dict:
    ws = base / f"{task['id']}__{agent}__r{run_idx}__{uuid.uuid4().hex[:6]}"
    ws.mkdir(parents=True)
    if task["setup"]:
        sh(task["setup"], ws)
    task = dict(task)
    task["prompt"] = with_ws(task["prompt"], ws)
    rec = {"agent": agent, "task": task["id"], "run": run_idx, "ws": str(ws),
           "run_id": ws.name, "ts": time.strftime("%H:%M:%S")}
    # 阶段1：首发（interrupt 任务在中途 SIGKILL）
    if interrupt and task.get("interrupt_s"):
        if agent == "cline":
            configured, config_err = _ensure_cline_config(ws)
            if not configured:
                rec.update({"ok_run": False, "pass": False, "status": "INFRA_FAIL",
                            "stats": "cline-config-failed", "stdout_tail": "",
                            "stderr_tail": config_err})
                return rec
        cmd_list = _spawn(agent, task, ws)
        # v0.1：lfl phase1 也必须用隔离 DATA_DIR，否则 session 落到共享仓库 data/，
        # ws 级 sid 反查（_lfl_full_sid）找不到文件，--session 依旧不会附加。
        spawn_base = _lfl_env(ws) if agent == "lfl" else dict(os.environ)
        spawn_env = _prepare_effect_probe(task, ws, spawn_base)
        p = subprocess.Popen(cmd_list, cwd=ws, env=spawn_env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             start_new_session=True)
        time.sleep(task["interrupt_s"])
        alive = p.poll() is None
        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        p.wait(timeout=10)
        rec["interrupted"] = alive
        phase1_full = (p.stdout.read() if p.stdout else "")
        (ws / "_phase1.log").write_text(phase1_full)  # 全量落盘：供 conv_/session id 提取（尾部截断会丢早期 id）
        rec["phase1_log"] = phase1_full[-800:]
        # 阶段2：续做（lfl 复用 session；cline 用 --id conv_*；da 重新发起但 prompt 提示已完成物可复用）
        prompt2 = task["prompt"] + " 【续做】此任务此前被强制中断，工作区可能已有部分成果；先检查现状再继续，不要重做已完成阶段。"
        t2 = dict(task)
        t2["prompt"] = prompt2
        phase1_sid8 = ""
        for ln in phase1_full.splitlines():
            if ln.startswith("[会话 "):
                phase1_sid8 = ln.split("[会话 ")[1].split("]")[0].split()[0][:8]
                break
        rec["phase1_sid"] = phase1_sid8
        if agent == "lfl":
            # v0.1 修复（P0-1）：v0 传 rec["phase1_log"]（800 字符尾部），sid 从未被提取，
            # "--session" 从未被附加 → v0 的 t12 LFL 3/3 实测为 new-session-same-workspace。
            # 复测追加：stdout 无 sid（SIGKILL mid-turn）时从隔离 store 解析，
            # 并回填 rec["phase1_sid"] 保持数据行自洽。
            if not phase1_sid8:
                phase1_sid8 = _lfl_newest_session_sid(ws)[:8]
                rec["phase1_sid"] = phase1_sid8
            r2 = run_lfl_session(t2, ws, task["timeout_s"], phase1_full,
                                 _lfl_full_sid(ws, phase1_sid8))
        elif agent == "cline":
            # 2026-09-12 smoke qualification（8 种调用形态 + 二进制守卫 + nightly 未修）：
            # cline 3.0.61 的 --id 只走交互 TTY 路径，headless（--json/管道 stdin/--yolo/--zen）
            # 全部被 CLI 守卫拒绝 → 该能力当前版本无法在 benchmark 中表达，分类 UNSUPPORTED。
            # v1 起不再执行真实恢复调用：约 1s 的必败调用只产生伪失败 latency（曾把 cline
            # 时长统计系统性拉低），与"能力无法表达"这一结论无关；守卫证据已固化在 smoke
            # 记录。上游支持 headless resume 后此分支恢复为真实 qualification。
            r2 = {"ok_run": False, "dur": None,
                  "resume_semantics": "unsupported-headless-resume",
                  "stdout_tail": "UNSUPPORTED(cline 3.0.61 headless resume): not invoked by design",
                  "stderr_tail": ""}
        else:
            # DA adapter 为一次性进程模型，无跨进程 session；v0.1 起显式标注恢复语义，
            # 不再计入 session-resume 维度。
            r2 = run_da(t2, ws, task["timeout_s"])
            r2["resume_semantics"] = "new-session-same-workspace-by-design"
        _merge_resume_result(rec, r2)
        # 完整 wall clock = 中断前固定时长 + 恢复段（v0 的 analyze 只取 resume_dur，系统偏低）。
        # UNSUPPORTED 不执行恢复段 → resume_dur=None：宁缺毋假，dur 亦置 None，不生成伪时长。
        if rec.get("resume_dur") is None:
            rec["dur"] = None
        else:
            rec["dur"] = round(task["interrupt_s"] + float(rec["resume_dur"]), 1)
    else:
        rec.update(ADAPTERS[agent](task, ws, task["timeout_s"]))
    effects, effects_status = _collect_task_effects(task, ws)
    if task.get("effect_probe"):
        rec["task_effects"] = effects
        rec["task_effects_status"] = effects_status
    ok, err = verify(task, ws)
    rec["pass"] = ok
    rec["verify_err"] = err
    rec["status"] = _classify(rec, ok)
    return rec

def _classify(rec: dict, ok: bool) -> str:
    """v0.1 状态分类（v0 只有 pass bool，ADAPTER_INVALID/INFRA_FAIL 混入成功率）：
    PASS | TASK_FAIL | INFRA_FAIL | ADAPTER_INVALID | UNSUPPORTED | TIMEOUT
    UNSUPPORTED：能力在当前 harness/CLI 版本无法表达（如 cline 3.0.61 headless resume），
    与 adapter 自身调用缺陷（ADAPTER_INVALID）区分。"""
    if "interrupted" in rec:  # t12 中断-恢复协议
        if not rec.get("resume_ok_run", True):
            if rec.get("resume_semantics") == "unsupported-headless-resume":
                return "UNSUPPORTED"
            if rec.get("resume_semantics") == "adapter-invalid-cli-invocation":
                return "ADAPTER_INVALID"
            if rec.get("resume_stdout_tail") == "HARNESS-TIMEOUT":
                return "TIMEOUT"
            return "INFRA_FAIL"
        return "PASS" if ok else "TASK_FAIL"
    if not rec.get("ok_run", True):
        return "TIMEOUT" if rec.get("stdout_tail") == "HARNESS-TIMEOUT" else "INFRA_FAIL"
    return "PASS" if ok else "TASK_FAIL"

def _spawn(agent, task, ws):
    if agent == "lfl":
        return [str(REPO / ".venv/bin/python"), "-m", "llm_loop.cli", "--model", LFL_MODEL, task["prompt"]]
    if agent == "cline":
        return _cline_cmd(task["prompt"], ws, task["timeout_s"])
    adapter = ws / "_da_adapter.py"
    adapter.write_text(DA_ADAPTER.replace("MODEL_ID", repr(DA_MODEL_ID)).replace("BASE_URL", repr(DA_BASE_URL)))
    return [str(HERE / ".venv-da/bin/python"), str(adapter), task["prompt"]]

def run_lfl_session(task, ws, timeout_s, phase1_full: str, phase1_sid_full: str):
    """v0.1 修复（P0-1）：从 phase1 全量日志提取 session id（v0 误传 rec["phase1_log"]，
    其仅为尾部 800 字符，sid 恒为空 → 实际测的是新会话恢复而非原生 session resume）。
    机械断言：resume 后 CLI 报告的 session 前缀 == phase1 sid 前缀。"""
    sid8 = ""
    for ln in phase1_full.splitlines():
        if ln.startswith("[会话 "):
            sid8 = ln.split("[会话 ")[1].split("]")[0].split()[0][:8]
            break
    if not sid8:
        # SIGKILL mid-turn：CLI 从未打印 [会话 …] 行（stdout 无 sid）；隔离 store 此刻
        # 仅含 phase1 会话，直接取最新 mtime 的 session 文件 id 作为 phase1 sid。
        sid8 = _lfl_newest_session_sid(ws)[:8]
    sid_full = phase1_sid_full or _lfl_full_sid(ws, sid8)
    env = _lfl_env(ws)
    cmd = [str(REPO / ".venv/bin/python"), "-m", "llm_loop.cli"]
    if sid_full:
        cmd += ["--session", sid_full]
    cmd += ["--model", LFL_MODEL, task["prompt"]]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=timeout_s)
        out = r.stdout
        stats = [ln for ln in out.splitlines() if ln.startswith("[会话")]
        resumed8 = stats[0].split("[会话 ")[1][:8] if stats else ""
        continuity = bool(sid8 and resumed8 and resumed8 == sid8)
        # S2/G1 修复：恢复腿事件随行落盘（合并后为 resume_first_call/resume_fcr_events）——
        # 否则 t12 恢复过程不可复算（frozen112 教训：事件只存 LFL 会话存储，存储不可用即 D0）
        fc2, fev2 = _tl.fcr_lfl(ws, sid_full)
        return {"ok_run": r.returncode == 0, "dur": round(time.time() - t0, 1),
                "stats": stats[0] if stats else "", "session": sid_full,
                "session_continuity": continuity,
                "resume_semantics": "session-resume" if continuity else
                                    ("new-session-same-workspace" if resumed8 else "resume-failed"),
                "stdout_tail": out[-1500:], "stderr_tail": r.stderr[-500:],
                "first_call": fc2, "fcr_events": fev2}
    except subprocess.TimeoutExpired:
        return {"ok_run": False, "dur": timeout_s, "stats": "", "session": sid_full,
                "session_continuity": False, "resume_semantics": "resume-failed",
                "stdout_tail": "HARNESS-TIMEOUT", "stderr_tail": "",
                "first_call": None, "fcr_events": None}

def _sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_plan(agents: list[str], tasks: list[dict], runs: int,
                randomize: bool, seed: int,
                latin_square: bool = False) -> list[tuple[str, dict, int]]:
    """Build the exact execution plan once; manifest and executor consume the same plan."""
    triples = [(a, t, i) for a in agents for t in tasks for i in range(1, runs + 1)]
    if latin_square:
        import random
        rng = random.Random(seed)
        blocks: dict[tuple[str, int], list[tuple[str, dict, int]]] = {}
        for ti, t in enumerate(tasks):
            base = rng.sample(agents, len(agents))
            for i in range(1, runs + 1):
                shift = (ti + i - 1) % len(agents)  # task-index+run 双错位：全网格位置均衡
                order = base[shift:] + base[:shift]
                blocks[(t["id"], i)] = [(a, t, i) for a in order]
        order_keys = list(blocks)
        rng.shuffle(order_keys)
        return [x for k in order_keys for x in blocks[k]]
    if not randomize:
        return triples
    import random
    rng = random.Random(seed)
    blocks: dict[tuple[str, int], list[tuple[str, dict, int]]] = {}
    for a, t, i in triples:
        blocks.setdefault((t["id"], i), []).append((a, t, i))
    order_keys = list(blocks)
    rng.shuffle(order_keys)
    return [x for k in order_keys for x in rng.sample(blocks[k], len(blocks[k]))]


def _manifest(agents, tasks, runs, interrupt, randomize, latin_square, seed, plan, out_name) -> dict:
    """v1 frozen provenance: versions, identities, source hashes, sampling and exact plan."""
    def sh(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
        except Exception as e:  # noqa: BLE001 - manifest 采集失败不阻断评测
            return f"unavailable: {e}"
    def listener_identity(port: int) -> dict:
        pids = sh(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]).split()
        if len(pids) != 1 or not pids[0].isdigit():
            return {"status": "unavailable", "listener_pids": pids}
        pid = pids[0]
        return {
            "status": "observed",
            "pid": int(pid),
            "started_and_command": sh(["ps", "-p", pid, "-o", "lstart=,command="]),
        }
    plan_rows = [{"agent": a, "task": t["id"], "run": i} for a, t, i in plan]
    plan_blob = json.dumps(plan_rows, ensure_ascii=False, separators=(",", ":")).encode()
    import hashlib
    m = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
         "manifest_schema": "agentpilot-v1",
         "agents": agents, "tasks": [t["id"] for t in tasks],
         "runs": runs, "interrupt": bool(interrupt),
         "randomize": bool(randomize), "latin_square": bool(latin_square), "seed": seed,
         "order_design": "randomized-latin-square" if latin_square else
                         ("randomized-block" if randomize else "agent-major"),
         "results_file": out_name,
         "lfl_commit": sh(["git", "-C", str(REPO), "rev-parse", "HEAD"]),
         "runner_sha256": _sha256(Path(__file__)),
         "tasks_sha256": _sha256(HERE / "tasks.py"),
         "telemetry_sha256": _sha256(HERE / "telemetry.py"),
         "scorer_sha256": _sha256(HERE / "analyze.py"),
         "cline_version": sh(["cline", "--version"]),
         "deepagents_version": sh([str(HERE / ".venv-da/bin/python"), "-c", "import deepagents; print(deepagents.__version__)"]),
         "model_endpoint": DA_BASE_URL,
         "model_runtime_process": listener_identity(8901),
         "harness_contracts": {
             "lfl": {"model_ref": LFL_MODEL, "sampling": "LFL/provider runtime contract"},
             "da": {"model_ref": DA_MODEL_ID, "temperature": 0.2, "max_retries": 2},
             "cline": {"expected_model_ref": CLINE_MODEL, "provider": "openai-compatible",
                       "base_url": DA_BASE_URL, "config_scope": "per-run-isolated",
                       "auto_approve": True, "sampling": "Cline runtime contract"},
         },
         "execution_plan": plan_rows,
         "execution_plan_sha256": hashlib.sha256(plan_blob).hexdigest(),
         "note": "v0.1: LFL t12 复测启用 per-run DATA_DIR 隔离（v0 原始 33 条未隔离）",
         }
    models = sh(["curl", "-s", "--max-time", "5", f"{DA_BASE_URL}/models"])
    m["model_identity_raw"] = models if models else "unavailable"
    try:
        model_obj = json.loads(models)
        m["model_catalog_ids"] = sorted(
            x.get("id") for x in model_obj.get("data", [])
            if isinstance(x, dict) and isinstance(x.get("id"), str)
        )
    except Exception:
        m["model_catalog_ids"] = []
    health = sh(["curl", "-s", "--max-time", "5", f"{DA_BASE_URL}/health"])
    m["model_server_health"] = health if health else "unavailable"
    cmd8901 = listener_identity(8901).get("started_and_command", "")
    m["model_dir_fingerprint"] = _model_dir_fingerprint(cmd8901)
    m["model_server_runtime"] = _server_runtime_versions(cmd8901)
    m["task_oracles"] = [{"id": t["id"], "first_tools": t.get("first_tools"),
                          "expected_failures": t.get("expected_failures", []),
                          "effect_probe": t.get("effect_probe"),
                          "timeout_s": t["timeout_s"], "interrupt_s": t.get("interrupt_s")}
                         for t in tasks]
    m["manifest_revision"] = 3  # M1 T02: frozen task effect-probe contract
    m["fcr_caliber"] = ("lfl first-action tokens/cache = null（per-turn usage 未持久化，"
                        "usage-missing ≠ 0），不参与 FCR efficiency 跨 harness 排名；"
                        "run-level tokens/cache 仍可比较。cline 工具级 ok 不可观测 → None。")
    m["t12_protocol"] = ("v1: interrupt_s=8（真实 mid-kill；v0 25s 时 lfl 3/3 为自然完成后中断，"
                         "仅证明同 session 再入，mid-kill 仅 1/1）。cline headless resume 8 种调用"
                         "形态冒烟均 UNSUPPORTED（3.0.61，2026-09-12），t12 记 UNSUPPORTED 不执行"
                         "恢复调用、不产生伪 latency；mid-kill 与自然完成分开统计，不合并成功率。")
    # `/models` 的 OpenAI-compatible `created` 字段由服务按请求时刻生成；raw 留作事实证据，
    # 但不能进入跨分片身份 freeze。稳定 catalog IDs + listener PID/command/model-dir fingerprint
    # 已覆盖需要锁定的物理/路由身份。
    frozen = {k: v for k, v in m.items()
              if k not in {"ts", "freeze_sha256", "model_identity_raw"}}
    m["freeze_sha256"] = hashlib.sha256(
        json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return m


def _model_dir_fingerprint(cmdline: str) -> dict:
    """8901 物理模型指纹：--model 目录小文件逐文件 sha256（配置/词表），大文件记 size+mtime。"""
    import hashlib, re as _re
    mm = _re.search(r"--model\s+(\S+)", cmdline or "")
    if not mm:
        return {"status": "no-model-flag"}
    d = Path(mm.group(1)).expanduser()
    if not d.is_dir():
        return {"status": "missing", "path": str(d)}
    files = {}
    for p in sorted(d.iterdir()):
        if p.is_file():
            st = p.stat()
            files[p.name] = (f"sha256:{hashlib.sha256(p.read_bytes()).hexdigest()[:16]}"
                             if st.st_size <= 2_000_000 else
                             f"size:{st.st_size},mtime:{int(st.st_mtime)}")
    return {"status": "ok", "path": str(d), "files": files}


def _server_runtime_versions(cmdline: str) -> dict:
    """8901 服务进程的解释器与 MLX/mlx_lm 版本（跳过 ps lstart 时间戳，取 python 解释器 token）。"""
    toks = (cmdline or "").split()
    cands = [t for t in dict.fromkeys(toks) if "python" in t.lower() and Path(t).exists()]
    if not cands:
        return {"status": "unavailable", "interpreter": None,
                "raw_head": " ".join(toks[:6]) or None}
    import subprocess
    code = ("import sys, mlx.core as mx, mlx_lm; "
            "print(sys.version.split()[0], mx.__version__, mlx_lm.__version__)")
    for mbin in cands:
        try:
            r = subprocess.run([mbin, "-c", code], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                return {"status": "ok", "interpreter": mbin, "versions": r.stdout.strip()}
        except Exception:
            continue
    return {"status": "unavailable", "interpreter": cands, "versions": None}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", default="lfl,da,cline")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workdir", default="/tmp/agentpilot")
    ap.add_argument("--interrupt", action="store_true", help="仅对带 interrupt_s 的任务启用中断协议")
    ap.add_argument("--out", default="results.jsonl", help="结果文件名（v0.1：追加式，分析端按 (agent,task,run) 取最新 ts）")
    ap.add_argument("--randomize", action="store_true", help="randomized block：每个 (task,run) 内随机化 agent 执行顺序，消除按时段成块运行带来的 cache/负载混杂")
    ap.add_argument("--latin-square", action="store_true", help="formal v1：每个 task 跨 repeat 平衡 agent 位置，block 全局顺序仍按 seed 随机")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--plan-only", action="store_true", help="冻结 manifest/执行计划并退出，不调用任何 agent")
    ap.add_argument("--start-index", type=int, default=0, help="从完整冻结 execution_plan 的 0-based index 开始执行")
    ap.add_argument("--max-items", type=int, default=0, help="本次最多执行多少个 plan item；0=执行到末尾")
    args = ap.parse_args()

    base = Path(args.workdir)
    base.mkdir(parents=True, exist_ok=True)
    requested_tasks = [x.strip() for x in args.tasks.split(",") if x.strip()]
    known_task_ids = {t["id"] for t in TASKS}
    unknown_tasks = [x for x in requested_tasks if x not in known_task_ids]
    if unknown_tasks:
        ap.error(f"unknown --tasks id(s): {','.join(unknown_tasks)}")
    sel = TASKS if not requested_tasks else [t for t in TASKS if t["id"] in requested_tasks]
    if not sel:
        ap.error("--tasks matched zero tasks")
    agents = [x.strip() for x in args.agents.split(",") if x.strip()]
    unknown_agents = [x for x in agents if x not in ADAPTERS]
    if unknown_agents:
        ap.error(f"unknown --agents value(s): {','.join(unknown_agents)}")
    if not agents:
        ap.error("--agents matched zero agents")
    if args.runs < 1:
        ap.error("--runs must be >= 1")
    if args.latin_square and args.runs % len(agents) != 0:
        ap.error("--latin-square requires --runs to be a multiple of the number of agents")
    # A01 启动校验：oracle 标注词汇表校验——违例=本次配置无效，明确报错退出，
    # 绝不把配置错误记为 LFL 任务失败（t02 "shell" 教训）
    oracle_errors = tasks.validate_oracles()
    if oracle_errors:
        print("ORACLE-CONFIG-INVALID（A01 启动校验失败，本次运行未执行）：", file=sys.stderr)
        for e in oracle_errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)
    results_path = base / args.out
    triples = _build_plan(agents, sel, args.runs, args.randomize, args.seed, args.latin_square)
    manifest = _manifest(agents, sel, args.runs, args.interrupt, args.randomize,
                         args.latin_square,
                         args.seed, triples, args.out)
    manifest_path = base / "manifest.json"
    if manifest_path.exists():
        old_manifest = json.loads(manifest_path.read_text())
        if old_manifest.get("freeze_sha256") != manifest.get("freeze_sha256"):
            ap.error("existing manifest freeze differs from current runtime/source/plan; use a fresh workdir")
        manifest = old_manifest
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    if args.plan_only:
        print(json.dumps({"manifest": str(manifest_path),
                          "plan_sha256": manifest["execution_plan_sha256"],
                          "planned_runs": len(triples)}, ensure_ascii=False))
        return
    if args.start_index < 0 or args.start_index >= len(triples):
        ap.error(f"--start-index must be in 0..{len(triples) - 1}")
    if args.max_items < 0:
        ap.error("--max-items must be >= 0")
    stop_index = min(len(triples), args.start_index + args.max_items) if args.max_items else len(triples)

    existing_by_index = {}
    if results_path.exists():
        for ln in results_path.read_text().splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            idx = row.get("plan_index")
            if isinstance(idx, int):
                existing_by_index[idx] = row
    invocation = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  "plan_sha256": manifest["execution_plan_sha256"],
                  "freeze_sha256": manifest["freeze_sha256"],
                  "start_index": args.start_index, "stop_index_exclusive": stop_index}
    with (base / "invocations.jsonl").open("a") as f:
        f.write(json.dumps(invocation, ensure_ascii=False) + "\n")

    with results_path.open("a") as rf:
        for plan_index in range(args.start_index, stop_index):
            agent, task, i = triples[plan_index]
            prior = existing_by_index.get(plan_index)
            if prior is not None:
                expected = (agent, task["id"], i)
                observed = (prior.get("agent"), prior.get("task"), prior.get("run"))
                if observed != expected:
                    ap.error(f"plan_index {plan_index} result mismatch: {observed!r} != {expected!r}")
                print(f"[skip] plan_index={plan_index} {agent} {task['id']} r{i} already recorded", flush=True)
                continue
            rec = run_one(agent, task, i, base, args.interrupt)
            rec["plan_index"] = plan_index
            rec["plan_sha256"] = manifest["execution_plan_sha256"]
            rf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            rf.flush()
            d = rec.get("dur", rec.get("resume_dur"))
            print(f"[{rec['ts']}] {agent:3s} {task['id']:22s} r{i} status={rec['status']} "
                  f"dur={(('%.1fs' % d) if d is not None else 'n/a(UNSUPPORTED)')}", flush=True)
    # summary：v0.1 按 (agent,task,run) 取最新 ts 去重（v0 旧追加行会重复计数），
    # 状态分桶，PASS 率不再吞并 ADAPTER_INVALID/INFRA_FAIL/TIMEOUT。
    rows = [json.loads(ln) for ln in results_path.read_text().splitlines() if ln.strip()]
    latest = {}
    for r in rows:
        latest[(r["agent"], r["task"], r.get("run"))] = r  # 追加式：后写覆盖
    rows = list(latest.values())
    by = {}
    for r in rows:
        by.setdefault((r["agent"], r["task"]), []).append(r.get("status", "PASS" if r.get("pass") else "TASK_FAIL"))
    lines = ["# pilot summary (v0.1 status-aware)",
             f"- file: {results_path}",
             f"- runs (deduped all-history): {len(rows)}",
             f"- runs (this session): {len(triples)}",
             "", "| agent | task | PASS/TASK_FAIL/其他 | n |", "|---|---|---|---|"]
    for (a, t), v in sorted(by.items()):
        n_p = sum(1 for x in v if x == "PASS")
        n_f = sum(1 for x in v if x == "TASK_FAIL")
        n_o = len(v) - n_p - n_f
        lines.append(f"| {a} | {t} | {n_p}P/{n_f}F/{n_o}oth | {len(v)} |")
    for a in agents:
        tot = [x for (ag, _), v in by.items() if ag == a for x in v]
        if tot:
            n_p = sum(1 for x in tot if x == "PASS")
            n_f = sum(1 for x in tot if x == "TASK_FAIL")
            n_o = len(tot) - n_p - n_f
            lines.append(f"\n**{a}** task_success: {n_p}/{len(tot)}（TASK_FAIL={n_f}, "
                         f"INFRA/ADAPTER/TIMEOUT={n_o}，不计入任务成功率）")
    (base / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))

if __name__ == "__main__":
    main()
