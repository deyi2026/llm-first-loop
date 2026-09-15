import json, statistics, sys
from collections import defaultdict
from pathlib import Path

AGENT_ORDER = ["lfl", "da", "cline"]
# 输入路径可由 argv[1] 指定（v1 矩阵用独立结果文件），默认 v0 存量数据
RESULTS = Path(sys.argv[1] if len(sys.argv) > 1 else "data/results.jsonl")
rows = [json.loads(l) for l in RESULTS.open() if l.strip()]

# dedupe: per (agent, task, run) keep latest ts  —— v0.1 唯一 canonical 去重规则
# （raw 112 行 -> 108 unique；不再使用 aggregate.py 的尾部 K=3 规则）
best = {}
for r in rows:
    key = (r["agent"], r["task"], r["run"])
    if key not in best or r.get("ts","") >= best[key].get("ts",""):
        best[key] = r
recs = list(best.values())
print(f"raw={len(rows)} -> deduped={len(recs)}")

# v0 数据无 status 字段：按 resume 语义回填（v0.1 runner 起直接产出 status）
for r in recs:
    if "status" not in r:
        se = (r.get("resume_stderr_tail") or "") + (r.get("resume_stdout_tail") or "")
        if (not r.get("resume_ok_run", True)) and (
            "JSON output mode requires" in se or "interactive mode" in se or "requires a prompt" in se):
            r["status"] = "ADAPTER_INVALID"
        elif not r.get("pass"):
            r["status"] = "TASK_FAIL"
        else:
            r["status"] = "PASS"

by_agent_task = defaultdict(list)
for r in recs:
    by_agent_task[(r["agent"], r["task"])].append(r)

TASK_ORDER = [f"t{i:02d}_{s}" for i,s in enumerate([
 "read_first_line","retry_transient","build_module","fix_bug","multi_file_sum","log_count",
 "json_flatten","resume_todo","big_file_line","fs_invariant","env_facts","interrupt_resume"],1)]
tasks = [t for t in TASK_ORDER if any(k[1]==t for k in by_agent_task)] + \
        sorted(t for t in {k[1] for k in by_agent_task} if t not in TASK_ORDER)
agents = [a for a in AGENT_ORDER if any(k[0]==a for k in by_agent_task)]

def q90(ds):
    ds = sorted(ds); k = (len(ds)-1)*0.9; f = int(k); c = min(f+1, len(ds)-1)
    return ds[f] + (ds[c]-ds[f])*(k-f)

print("== Status matrix (PASS / runs) ==")
print("task".ljust(22) + "".join(a.ljust(10) for a in agents))
agg = {a: [0,0] for a in agents}
status_count = {a: defaultdict(int) for a in agents}
for t in tasks:
    line = t.ljust(22)
    for a in agents:
        rs = by_agent_task.get((a,t),[])
        p = sum(1 for r in rs if r.get("pass"))
        line += f"{p}/{len(rs)}".ljust(10)
        agg[a][0]+=p; agg[a][1]+=len(rs)
        for r in rs: status_count[a][r["status"]] += 1
    print(line)
print()
print("== Aggregate ==")
for a in agents:
    p,n = agg[a]
    sc = status_count[a]
    print(f"{a}: {p}/{n} = {p/n*100:.1f}%" if n else f"{a}: 0/0", end="")
    print("   status:", dict(sorted(sc.items())))
print()
print("== Task success rate (excl. infra/adapter invalid; per agent) ==")
for a in agents:
    valid = [r for r in recs if r["agent"]==a and r["status"] not in ("ADAPTER_INVALID","UNSUPPORTED")]
    p = sum(1 for r in valid if r["status"]=="PASS")
    inv, uns = status_count[a]["ADAPTER_INVALID"], status_count[a]["UNSUPPORTED"]
    print(f"{a}: {p}/{len(valid)} task-level (adapter_invalid: {inv}, unsupported: {uns})")
print()
print("== t12 continuity (interrupt-protocol rows only; separate from pass rate) ==")
for a in agents:
    t12 = [r for r in recs if r["agent"] == a and "interrupted" in r]
    if not t12:
        continue
    interr = [r for r in t12 if r.get("interrupted")]
    nat = [r for r in t12 if not r.get("interrupted")]
    sem = defaultdict(int)
    for r in t12:
        sem[r.get("resume_semantics", "?")] += 1
    cont = sum(1 for r in t12 if r.get("resume_session_continuity"))
    rd = [r.get("resume_dur") for r in t12
          if r.get("resume_dur") is not None and r["status"] == "PASS"]
    line = (f"{a}: n={len(t12)} interrupted={len(interr)} natural-completed={len(nat)} "
            f"semantics={dict(sorted(sem.items()))} lfl-session-continuity={cont}/{len(t12)}")
    print(line)
    if rd:
        print(f"    valid-resume dur (PASS only): n={len(rd)} median={statistics.median(rd):.1f}s "
              f"mean={statistics.mean(rd):.1f}s（UNSUPPORTED/invalid 不产生伪时长）")
print()
print("== Duration (s): median / mean / p90 ==")
print("-- caliber A: all 36/agent, t12=resume_dur (v0 口径, 保留对照) --")
for a in agents:
    ds = [d for r in recs if r["agent"]==a and (d:=r.get("dur", r.get("resume_dur"))) is not None]
    if ds:
        print(f"{a}: {statistics.median(ds):.1f} / {statistics.mean(ds):.1f} / {q90(ds):.1f}  (n={len(ds)})")
print("-- caliber C: t01-t11 success runs only (推荐对比口径) --")
for a in agents:
    ds = [r["dur"] for r in recs if r["agent"]==a and not r["task"].startswith("t12") and r["status"]=="PASS" and r.get("dur") is not None]
    if ds:
        print(f"{a}: {statistics.median(ds):.1f} / {statistics.mean(ds):.1f} / {q90(ds):.1f}  (n={len(ds)})")
print()
print("== First-Call-Ready (two layers: raw mechanical + scorer-derived) ==")
# v0.2 起 runner 只落 raw 层 + fcr_events（原始事件流），scorer 层（selection/ready/
# directness）由 analyze 时结合 tasks.py oracle 离线派生——runtime 不裁决任务语义。
# v0.1 旧记录的 first_call 是合并 dict（selection/ready 已内嵌），读兼容字段。
import tasks as _tasks, telemetry as _tl
TASK_BY_ID = {t["id"]: t for t in _tasks.TASKS}
def _scored(r):
    raw = r.get("first_call") or r.get("resume_first_call")
    if raw is None:
        return None
    if "first_tool_selection_correct" in raw or "first_action_ready" in raw:
        return raw                                    # v0.1 legacy merged dict
    ev = r.get("fcr_events") or r.get("resume_fcr_events")  # G1 起 t12 恢复腿事件随行（S2 前半）
    task = TASK_BY_ID.get(r["task"])
    if ev and task:
        return {**raw, **_tl.score_fcr(raw, ev, task)}  # v0.2: raw + 离线 scorer
    return raw
for a in agents:
    fcrs = [_scored(r) for r in recs if r["agent"]==a]
    fcrs = [f for f in fcrs if f]
    if not fcrs:
        print(f"{a}: no telemetry rows"); continue
    sv  = [f for f in fcrs if f.get("first_args_mechanically_valid") is not None]
    ex  = [f for f in fcrs if f.get("first_tool_executed") is not None]
    rawf= [f.get("tool_failure_count_raw") for f in fcrs if f.get("tool_failure_count_raw") is not None]
    sel = [f.get("first_tool_selection_correct") for f in fcrs if f.get("first_tool_selection_correct") is not None]
    rdy = [f.get("first_call_ready", f.get("first_action_ready")) for f in fcrs
           if f.get("first_call_ready", f.get("first_action_ready")) is not None]
    dt  = [f.get("first_call_direct", f.get("first_tool_selection_correct")) for f in fcrs
           if f.get("first_call_direct", f.get("first_tool_selection_correct")) is not None]
    cov = sorted({str(f.get("ok_signal", f.get("coverage"))) for f in fcrs})
    tt  = [f.get("time_to_first_mechanical_valid_action_s", f.get("time_to_first_valid_action_s")) for f in fcrs
           if f.get("time_to_first_mechanical_valid_action_s", f.get("time_to_first_valid_action_s")) is not None]
    tk  = [f.get("tokens_to_first_mechanical_valid_action", f.get("tokens_to_first_valid_action")) for f in fcrs
           if f.get("tokens_to_first_mechanical_valid_action", f.get("tokens_to_first_valid_action")) is not None]
    print(f"{a}: n={len(fcrs)}  ok_signal={','.join(cov)}")
    print(f"  [raw]    args_mech_valid {sum(x['first_args_mechanically_valid'] for x in sv)}/{len(sv)}"
          f"  executed {sum(x['first_tool_executed'] for x in ex)}/{len(ex)}"
          + (f"  fail_raw/run mean {statistics.mean(rawf):.2f}" if rawf else "  fail_raw: unavailable"))
    if sel: print(f"  [scorer] selection {sum(sel)}/{len(sel)}"
                  f"  first_call_ready {sum(rdy)}/{len(rdy)}"
                  f"  directness mean {statistics.mean(dt):.2f}")
    elif any("first_call_ready" in f or "first_action_ready" in f for f in fcrs):
        print(f"  [scorer] ready {sum(rdy)}/{len(rdy)}  selection: unavailable (no first_tools oracle)")
    else:
        print(f"  [scorer] unavailable (raw-only rows, no fcr_events)")
    if tt:  print(f"  [cost]   time_to_first_mech_valid: median {statistics.median(tt):.2f}s")
    if tk:  print(f"  tokens_to_first_mech_valid: median {statistics.median(tk):,.0f}")
print()
print("== Non-PASS runs detail ==")
for a in agents:
    fails = [r for r in recs if r["agent"]==a and r["status"]!="PASS"]
    if not fails:
        print(f"{a}: none")
    for r in fails:
        note = (r.get("verify_err") or ("harness_err" if not r.get("ok_run") else ""))[:100]
        print(f"{a} {r['task']} run{r['run']}: [{r['status']}] {note}")
