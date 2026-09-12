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
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
from tasks import TASKS  # noqa: E402

LFL_MODEL = "cognilocal/ornith-1.5-35b-a3b-mlx"
DA_MODEL_ID = "ornith-ai/Ornith-1.5-35B-A3B-MLX"
DA_BASE_URL = "http://127.0.0.1:8901/v1"

DA_ADAPTER = r'''
import json, os, subprocess, sys
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
    state = agent.invoke({"messages": [("user", prompt)]}, config=cfg)
    msgs = state["messages"]
    n_tool = sum(1 for m in msgs if getattr(m, "type", "") == "tool" or getattr(m, "tool_calls", None))
    last = ""
    for m in reversed(msgs):
        if getattr(m, "type", "") == "ai" and getattr(m, "content", ""):
            last = m.content if isinstance(m.content, str) else str(m.content); break
    print(json.dumps({"rounds_approx": len(msgs), "tool_calls": n_tool, "final": last[:2000]}))

if __name__ == "__main__":
    main()
'''

def sh(cmd: str, cwd: Path, timeout: int = 30) -> None:
    r = subprocess.run(["/bin/zsh", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"setup failed: {r.stderr[:500]}")

def verify(task: dict, ws: Path) -> tuple[bool, str]:
    r = subprocess.run([sys.executable, "-c", task["verify"]], cwd=ws, capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stderr[-300:] if r.returncode else "")

def run_lfl(task: dict, ws: Path, deadline_s: int) -> dict:
    env = dict(os.environ)
    cmd = [str(REPO / ".venv/bin/python"), "-m", "llm_loop.cli", "--model", LFL_MODEL, task["prompt"]]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=deadline_s)
        out, rc, dur = r.stdout, r.returncode, round(time.time() - t0, 1)
        stats = [ln for ln in out.splitlines() if ln.startswith("[会话")]
        sid = stats[0].split("[会话 ")[1][:8] if stats else ""
        return {"ok_run": rc == 0, "dur": dur, "stats": stats[0] if stats else "", "session": sid,
                "stdout_tail": out[-1500:], "stderr_tail": r.stderr[-500:]}
    except subprocess.TimeoutExpired:
        return {"ok_run": False, "dur": deadline_s, "stats": "", "session": "", "stdout_tail": "HARNESS-TIMEOUT", "stderr_tail": ""}

def run_da(task: dict, ws: Path, deadline_s: int) -> dict:
    adapter = ws / "_da_adapter.py"
    adapter.write_text(DA_ADAPTER.replace("MODEL_ID", repr(DA_MODEL_ID)).replace("BASE_URL", repr(DA_BASE_URL)))
    cmd = [str(HERE / ".venv-da/bin/python"), str(adapter), task["prompt"]]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=deadline_s)
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
        return {"ok_run": rc == 0, "dur": dur, "stats": f'rounds~{meta.get("rounds_approx")} tools={meta.get("tool_calls")}',
                "session": "", "stdout_tail": (meta.get("final", "") + "\n--\n" + out)[-1500:], "stderr_tail": r.stderr[-500:]}
    except subprocess.TimeoutExpired:
        return {"ok_run": False, "dur": deadline_s, "stats": "", "session": "", "stdout_tail": "HARNESS-TIMEOUT", "stderr_tail": ""}

# ---------- cline adapter（CLI 已冒烟验证：--json 流含 taskId=conv_* 与 run_result；--id 可恢复会话） ----------
CLINE_MODEL = "ornith-ai/Ornith-1.5-35B-A3B-MLX"  # 与 LFL_MODEL/DA_MODEL_ID 同一 8901 物理模型（唯一 ornith 目录）

def _cline_cmd(prompt: str, ws: Path, deadline_s: int, session_id: str = "") -> list:
    cmd = ["cline", "-P", "openai-compatible", "--auto-approve", "true", "--json",
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
    try:
        r = subprocess.run(_cline_cmd(task["prompt"], ws, deadline_s, session_id),
                           cwd=ws, capture_output=True, text=True, timeout=deadline_s + 60)
        out, rc, dur = r.stdout, r.returncode, round(time.time() - t0, 1)
        info = _cline_parse(out)
        meta = info["meta"]
        return {"ok_run": rc == 0 and meta.get("finish") != "error",
                "dur": dur,
                "stats": f"iters={meta.get('iters')} finish={meta.get('finish')} model={meta.get('model')}",
                "session": info["taskid"],
                "stdout_tail": out[-1500:], "stderr_tail": r.stderr[-500:]}
    except subprocess.TimeoutExpired:
        return {"ok_run": False, "dur": deadline_s, "stats": "", "session": "",
                "stdout_tail": "HARNESS-TIMEOUT", "stderr_tail": ""}

ADAPTERS = {"lfl": run_lfl, "da": run_da, "cline": run_cline}

def with_ws(prompt: str, ws: Path) -> str:
    """公平性：两个 agent 的工具默认 cwd 语义不同（lfl=仓库根，da=进程cwd），
    统一在 prompt 中给出绝对工作目录。"""
    return f"工作目录（绝对路径）：{ws.resolve()}。所有文件读写与命令都应针对此目录下的文件（可用绝对路径）。任务：{prompt}"

def run_one(agent: str, task: dict, run_idx: int, base: Path, interrupt: bool) -> dict:
    ws = base / f"{task['id']}__{agent}__r{run_idx}__{uuid.uuid4().hex[:6]}"
    ws.mkdir(parents=True)
    if task["setup"]:
        sh(task["setup"], ws)
    task = dict(task)
    task["prompt"] = with_ws(task["prompt"], ws)
    rec = {"agent": agent, "task": task["id"], "run": run_idx, "ws": str(ws), "ts": time.strftime("%H:%M:%S")}
    # 阶段1：首发（interrupt 任务在中途 SIGKILL）
    if interrupt and task.get("interrupt_s"):
        cmd_list = _spawn(agent, task, ws)
        p = subprocess.Popen(cmd_list, cwd=ws,
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
        if agent == "lfl":
            r2 = run_lfl_session(t2, ws, task["timeout_s"], rec["phase1_log"])
        elif agent == "cline":
            r2 = run_cline(t2, ws, task["timeout_s"],
                           session_id=_cline_parse(phase1_full)["taskid"])
        else:
            r2 = run_da(t2, ws, task["timeout_s"])
        rec.update({f"resume_{k}": v for k, v in r2.items()})
    else:
        rec.update(ADAPTERS[agent](task, ws, task["timeout_s"]))
    ok, err = verify(task, ws)
    rec["pass"] = ok
    rec["verify_err"] = err
    return rec

def _spawn(agent, task, ws):
    if agent == "lfl":
        return [str(REPO / ".venv/bin/python"), "-m", "llm_loop.cli", "--model", LFL_MODEL, task["prompt"]]
    if agent == "cline":
        return _cline_cmd(task["prompt"], ws, task["timeout_s"])
    adapter = ws / "_da_adapter.py"
    adapter.write_text(DA_ADAPTER.replace("MODEL_ID", repr(DA_MODEL_ID)).replace("BASE_URL", repr(DA_BASE_URL)))
    return [str(HERE / ".venv-da/bin/python"), str(adapter), task["prompt"]]

def run_lfl_session(task, ws, timeout_s, phase1_log):
    """续做：从 phase1 日志提取 session id，用 --session 复用。"""
    sid = ""
    for ln in phase1_log.splitlines():
        if ln.startswith("[会话 "):
            sid = ln.split("[会话 ")[1].split("]")[0]
            break
    cmd = [str(REPO / ".venv/bin/python"), "-m", "llm_loop.cli"]
    if sid:
        cmd += ["--session", sid]
    cmd += ["--model", LFL_MODEL, task["prompt"]]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout_s)
        stats = [ln for ln in r.stdout.splitlines() if ln.startswith("[会话")]
        return {"ok_run": r.returncode == 0, "dur": round(time.time() - t0, 1),
                "stats": stats[0] if stats else "", "session": sid,
                "stdout_tail": r.stdout[-1500:], "stderr_tail": r.stderr[-500:]}
    except subprocess.TimeoutExpired:
        return {"ok_run": False, "dur": timeout_s, "stats": "", "session": sid, "stdout_tail": "HARNESS-TIMEOUT", "stderr_tail": ""}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", default="lfl,da,cline")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workdir", default="/tmp/agentpilot")
    ap.add_argument("--interrupt", action="store_true", help="仅对带 interrupt_s 的任务启用中断协议")
    args = ap.parse_args()

    base = Path(args.workdir)
    base.mkdir(parents=True, exist_ok=True)
    sel = TASKS if not args.tasks else [t for t in TASKS if t["id"] in args.tasks.split(",")]
    agents = args.agents.split(",")
    results_path = base / "results.jsonl"
    with results_path.open("a") as rf:
        for agent in agents:
            for task in sel:
                for i in range(1, args.runs + 1):
                    rec = run_one(agent, task, i, base, args.interrupt)
                    rf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    rf.flush()
                    print(f"[{rec['ts']}] {agent:3s} {task['id']:22s} r{i} pass={rec['pass']} dur={rec.get('dur', rec.get('resume_dur'))}s", flush=True)
    # summary
    rows = [json.loads(ln) for ln in results_path.read_text().splitlines() if ln.strip()]
    by = {}
    for r in rows:
        by.setdefault((r["agent"], r["task"]), []).append(r["pass"])
    lines = ["# pilot summary", f"- runs: {len(rows)}", "", "| agent | task | pass | n |", "|---|---|---|---|"]
    for (a, t), v in sorted(by.items()):
        lines.append(f"| {a} | {t} | {sum(v)}/{len(v)} | {len(v)} |")
    for a in agents:
        tot = [x for (ag, _), v in by.items() if ag == a for x in v]
        if tot:
            lines.append(f"\n**{a}** 总通过率: {sum(tot)}/{len(tot)} = {sum(tot)/len(tot):.0%}")
    (base / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))

if __name__ == "__main__":
    main()
