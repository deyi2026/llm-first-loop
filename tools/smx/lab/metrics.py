#!/usr/bin/env python3
"""lab/metrics.py — 从 DSH session 事件日志机械提取阶段二对照指标。

闸门0冻结件；口径见 PROTOCOL-20260911.md §4。
只做机械分类，不做语义解释；对 A/B 两组施加同一套规则。

用法：python3 metrics.py <session-dir | session.jsonl[.zstd]> [--out metrics.json] [--audit calls.tsv]
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SHELL_TOOL_HINTS = re.compile(r"bash|shell|exec|command|terminal|run_", re.I)
PERCEPTION_TOOLS = {"read", "view", "cat"}
SHELL_SEP = re.compile(r"\n|&&|\|\||;|\|")
ENV_PREFIX = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)+")
READ_CMDS = {"ls", "cat", "head", "tail", "stat", "wc", "file", "find", "grep",
             "egrep", "fgrep", "du", "df", "ps", "pgrep", "lsof", "pwd", "tree",
             "less", "more", "which", "whoami", "env", "printenv", "shasum",
             "md5", "cksum", "od", "cmp", "diff"}
WRITE_MARKS = re.compile(r"(>>|>|[^-]\s tee\s|tee\s+-a|find\s+.*\s-exec|find\s+.*\s-delete)")
SMX_RE = re.compile(r"smx\.py\b")
SMX_ACTION_RE = re.compile(r"smx\.py\s+(\w+)")
RECEIPT_RE = re.compile(r"\.smx/runs|receipt\.json")
SLEEP_RE = re.compile(r"^\s*sleep\s+([0-9.]+)")


def load_lines(path: Path):
    if path.suffix in (".zst", ".zstd"):
        out = subprocess.run(["zstd", "-dc", str(path)], capture_output=True, check=True)
        return out.stdout.decode("utf-8", "replace").splitlines()
    return path.read_text(errors="replace").splitlines()


def resolve_session(arg: str) -> Path:
    p = Path(arg)
    if p.is_dir():
        cand = [p / "session.jsonl.zstd", p / "session.jsonl.zst", p / "session.jsonl"]
        for c in cand:
            if c.exists():
                return c
        raise SystemExit(f"no session log under {p}")
    if not p.exists():
        raise SystemExit(f"not found: {p}")
    return p


def extract_command(name: str, arguments) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            return arguments
    if isinstance(arguments, dict):
        for k in ("command", "cmd", "script", "code", "input"):
            v = arguments.get(k)
            if isinstance(v, str):
                return v
        return json.dumps(arguments, ensure_ascii=False)[:400]
    return ""


def classify_shell(cmd: str):
    """机械分类一个 shell 命令字符串 → dict(perception, sleep_calls, sleep_secs, write)"""
    segs = [s for s in SHELL_SEP.split(cmd) if s.strip()]
    perception = 0
    sleep_calls = 0
    sleep_secs = 0.0
    for raw in segs:
        seg = ENV_PREFIX.sub("", raw.strip())
        # 引号内分隔符误切是已知近似，A/B 同规则，口径文档如实声明
        first = seg.split()[0] if seg.split() else ""
        base = first.rsplit("/", 1)[-1]
        is_write = bool(WRITE_MARKS.search(seg))
        if base == "sleep":
            sleep_calls += 1
            m = SLEEP_RE.match(seg)
            if m:
                sleep_secs += float(m.group(1))
        elif base in READ_CMDS and not is_write:
            perception += 1
    return {"perception": perception, "sleep_calls": sleep_calls,
            "sleep_secs": round(sleep_secs, 1)}


def analyze(log: Path):
    metrics = {
        "log": str(log),
        "turns": 0, "steps": 0, "tool_calls": 0, "assistant_messages": 0,
        "tool_errors": 0,
        "shell_calls": 0, "shell_perception_segments": 0,
        "sleep_calls": 0, "sleep_secs": 0.0,
        "tool_perception_calls": 0,
        "smx_calls": 0, "smx_actions": {},
        "smx_sub_perception": 0,  # smx show（重放回执）
        "receipt_refs": 0,
        "wall_s": 0.0,
        "tool_histogram": {},
    }
    audit = []  # (seq, turn, step, name, klass, snippet)
    t_first = t_last = None
    for line in load_lines(log):
        try:
            e = json.loads(line)
        except Exception:
            continue
        et = e.get("type", "")
        t = e.get("time")
        if isinstance(t, (int, float)):
            t_first = t if t_first is None else t_first
            t_last = t if t_last is None else max(t_last, t)
        if et == "turn/start":
            metrics["turns"] += 1
        elif et == "step/start":
            metrics["steps"] += 1
        elif et == "assistant/message":
            metrics["assistant_messages"] += 1
        elif et == "tool/call":
            metrics["tool_calls"] += 1
            d = e.get("data", {})
            name = str(d.get("name", "?"))
            metrics["tool_histogram"][name] = metrics["tool_histogram"].get(name, 0) + 1
            cmd = extract_command(name, d.get("arguments"))
            klass = "other"
            if SMX_RE.search(cmd or ""):
                metrics["smx_calls"] += 1
                m = SMX_ACTION_RE.search(cmd)
                act = m.group(1) if m else "?"
                metrics["smx_actions"][act] = metrics["smx_actions"].get(act, 0) + 1
                klass = f"smx:{act}"
                if act == "show":
                    metrics["smx_sub_perception"] += 1
                if act in ("exec", "bg", "collect") and RECEIPT_RE.search(cmd or ""):
                    pass
            elif SHELL_TOOL_HINTS.search(name) or any(
                    k in cmd[:60] for k in ("cd ", "mkdir ", "ls ", "cat ", "echo ")):
                metrics["shell_calls"] += 1
                c = classify_shell(cmd)
                metrics["shell_perception_segments"] += c["perception"]
                metrics["sleep_calls"] += c["sleep_calls"]
                metrics["sleep_secs"] += c["sleep_secs"]
                klass = "shell"
            elif name.lower() in PERCEPTION_TOOLS:
                metrics["tool_perception_calls"] += 1
                klass = "perception-tool"
            if RECEIPT_RE.search(cmd or "") or RECEIPT_RE.search(
                    json.dumps(d.get("arguments", ""), ensure_ascii=False) if isinstance(d.get("arguments"), str) else ""):
                metrics["receipt_refs"] += 1
                klass += "+receipt"
            audit.append((e.get("seq", ""), d.get("turn", ""), d.get("step", ""),
                          name, klass, (cmd or "")[:200].replace("\t", " ")))
        elif et == "tool/result":
            d = e.get("data", {})
            msg = d.get("message", {})
            content = msg.get("content", []) if isinstance(msg, dict) else []
            for item in content if isinstance(content, list) else []:
                if isinstance(item, dict) and item.get("isError"):
                    metrics["tool_errors"] += 1
                    break
    if t_first is not None and t_last is not None:
        metrics["wall_s"] = round((t_last - t_first) / 1000.0, 1)
    return metrics, audit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--out")
    ap.add_argument("--audit")
    a = ap.parse_args()
    log = resolve_session(a.session)
    m, audit = analyze(log)
    out = Path(a.out) if a.out else log.parent / "metrics.json"
    out.write_text(json.dumps(m, ensure_ascii=False, indent=1))
    if a.audit:
        ap_ = Path(a.audit)
    else:
        ap_ = log.parent / "calls.tsv"
    with ap_.open("w") as f:
        f.write("seq\tturn\tstep\ttool\tklass\tcommand\n")
        for row in audit:
            f.write("\t".join(str(x) for x in row) + "\n")
    print(json.dumps({k: v for k, v in m.items() if k != "tool_histogram"},
                     ensure_ascii=False))
    print(f"metrics -> {out}")
    print(f"audit   -> {ap_}")


if __name__ == "__main__":
    main()
