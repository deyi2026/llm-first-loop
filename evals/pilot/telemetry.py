"""First-Call-Ready telemetry v0.2 —— 两层结构（Gate 3 重构）。

Layer 1  raw mechanical telemetry  extract_raw(events)
    纯机械事实：工具名/轮次/schema-valid/执行状态/tokens/cache/统计计数。
    不依赖 task oracle，不判断“这个工具该不该用”；runner 采集时落盘。
    cache 字段不可测时为 None（显式 unavailable，不得记 0）。

Layer 2  benchmark scorer         score_fcr(raw, events, task)
    依赖任务 oracle（tasks.py 的 first_tools / expected_failures），离线可迭代：
    selection correctness、First-Call-Ready、directness、repair、unnecessary
    verification、expected/unexpected failure 拆分。绝不进入 LFL runtime。

统一事件流（三通道各自解析，同一套消费代码）：
  {"t0": float|"", "ok_signal": bool,
   "calls":[{"name","classes","args","ok","result","start_rel","end_rel","turn"}],
   "turns":[{"tokens_in","cached","tokens_out"}], "source": str}
  ok=None 表示该通道 per-call 成败不可测（cline）；result 为工具结果摘要（≤RESULT_CAP
  字符，附 result_len/result_truncated 截断显式标记；lfl/da 有；cline None）。raw 层
  保留 call_id 机械身份供跨步骤追溯（A09），scorer 不消费 call_id（分层不破坏）。
  scorer 对不可测指标输出 None 而非猜测；证据被截断且未命中 oracle 的失败归
  expected_failure_unresolvable 而非伪造 unexpected（A05）。

First-Call-Ready 定义（沿用 63-tool 实验已验证语义）：
  Mechanical Correctness（主指标） = 正确工具选择 × 参数机械可执行
  Directness（次指标）             = 首个调用即选中任务标注工具类
  合法的 get_goal / task_frontier / current-fact verification 不判失败。
"""
from __future__ import annotations

import json
from pathlib import Path

# 结果保留上限（F08 修复，200→2000）：expected_failure 匹配需要完整可判证据，
# 原先 200 字符截断会把出现在截断点之后的失败标记错计为 unexpected_failure。
# 超限时保留前 RESULT_CAP 字符并显式置 result_truncated=True（A05：不伪造判定）。
RESULT_CAP = 2000

TOOL_CLASSES: dict[str, set[str]] = {
    # lfl（仓库工具面）
    "read_file": {"read"}, "read_attachment": {"read"}, "source_synopsis": {"read"},
    "get_tool_schema": {"read"}, "read_evidence": {"read"}, "list_evidence": {"list"},
    "search_files": {"search"}, "search_evidence": {"search"}, "search_archive": {"search"},
    "search_records": {"search"}, "search_docs": {"search"},
    "get_goal": {"verify"}, "task_frontier": {"verify"},   # 合法状态查询：豁免类
    "edit_file": {"edit"}, "execute_command": {"command"}, "retry_tool": {"command"},
    # da（AgentPilot 最小 4-tool adapter）
    "write_file": {"write"}, "list_dir": {"list"},
    # cline
    "read_files": {"read"},
    "editor": {"write", "edit"},
    "execute_command": {"command"}, "run_command": {"command"},
    "list_files": {"list"}, "list": {"list"},
    "search": {"search"},
}

def tool_classes(name: str) -> set[str]:
    return TOOL_CLASSES.get(name, {"other"})

# 合法绕路类：纯 verification/搜索首调用不判 selection 错、不计成功分（None），
# directness 单独记 0。依据 63-tool First-Call-Ready A/B：惩罚这类调用会产生伪回归。
_LEGIT_SIDE = {"verify", "search"}

def _canon_args(args) -> str:
    try:
        if isinstance(args, str):
            args = json.loads(args)
        return json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return str(args)

# ---------- 统一事件流构造（三通道） ----------

def _find_lfl_session(ws, sid: str) -> Path | None:
    if not sid:
        return None
    ws = Path(ws)
    store = ws / ".lfldata" / "sessions"
    if not store.is_dir():
        return None
    m = [p for p in store.rglob(sid.split("-")[0][:8] + "*.json") if ".identity" not in p.parts]
    return max(m, key=lambda p: p.stat().st_mtime) if m else None

def events_lfl(session_path: Path) -> dict | None:
    try:
        s = json.loads(session_path.read_text())
        ms = s.get("messages", [])
    except Exception:
        return None
    t0 = next((m["ts"] for m in ms if (m.get("ts") or 0) > 0), 0.0)
    calls: list[dict] = []
    turns: list[dict] = []
    turn_idx = 0
    for m in ms:
        if m.get("role") == "assistant":
            turn_idx += 1
            turns.append({"tokens_in": m.get("tokens_in"), "cached": m.get("tokens_cache_hit"),
                          "tokens_out": m.get("tokens_out")})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                name = fn.get("name") or tc.get("name") or ""
                args = fn.get("arguments", tc.get("arguments"))
                calls.append({"name": name, "classes": sorted(tool_classes(name)),
                              "args": _canon_args(args), "ok": None, "result": None,
                              "start_rel": (m.get("ts", 0.0) - t0), "end_rel": None, "turn": turn_idx,
                              "call_id": tc.get("id")})
        elif m.get("role") == "tool":
            body = m.get("content")
            body = body if isinstance(body, str) else (json.dumps(body, ensure_ascii=False, default=str)
                                                       if body is not None else "")
            for c in calls:
                if c.get("call_id") and c["call_id"] == m.get("tool_call_id") and c["ok"] is None:
                    c["ok"] = (m.get("status") == "success")
                    c["result"] = body[:RESULT_CAP]
                    c["result_len"] = len(body)
                    c["result_truncated"] = len(body) > RESULT_CAP
                    c["end_rel"] = (m.get("ts", 0.0) - t0)
    # F08 修复：不再移除 call_id——raw 层保留机械身份（调用↔结果精确关联、A09 追溯）；
    # scorer 不消费该字段，raw/scorer 分层不变。
    return {"t0": t0, "calls": calls, "turns": turns, "source": f"lfl:{session_path.name[:8]}"}

def events_da(telemetry: dict | None) -> dict | None:
    """telemetry 由 DA_ADAPTER 按 tool_call_id 精确配对重建（v0.2 起）。"""
    if not telemetry:
        return None
    calls = []
    for c in telemetry.get("calls", []):
        name = c.get("name", "")
        calls.append({"name": name, "classes": sorted(tool_classes(name)), "args": _canon_args(c.get("args")),
                      "ok": c.get("ok"), "result": c.get("result"),
                      "result_len": c.get("result_len"), "result_truncated": c.get("result_truncated"),
                      "call_id": c.get("call_id"),  # F08 修复：raw 层保留机械身份（scorer 不消费）
                      "start_rel": None, "end_rel": None, "turn": c.get("turn")})
    for i, c in enumerate(calls, 1):
        if c["turn"] is None:
            c["turn"] = i
    return {"t0": "", "calls": calls, "turns": telemetry.get("turns", []),
            "source": "da:adapter-telemetry"}

def _parse_iso(ts: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0

def events_cline(stream_text: str) -> dict | None:
    """cline --json NDJSON 流（3.0.61 实测结构）：
      tool_result 事件无 output、无 toolCallId → per-call ok 不可测（恒 None）；
      usage 事件无 cache 分解 → cached 恒 None。failure/repair/verification/cache
      类指标在 cline 侧不可测：raw 与 scorer 均输出 None 而非 0。
    """
    lines = [l for l in stream_text.splitlines() if l.strip()]
    t0 = None
    calls: list[dict] = []
    open_stack: list[dict] = []
    turns: list[dict] = []
    last_total_in = 0
    for ln in lines:
        try:
            j = json.loads(ln)
        except Exception:
            continue
        if not isinstance(j, dict):
            continue
        ts = _parse_iso(j.get("ts", ""))
        if t0 is None and ts:
            t0 = ts
        ev = j.get("event") if isinstance(j.get("event"), dict) else {}
        et = ev.get("type")
        if et == "iteration_start":
            turns.append({"tokens_in": None, "cached": None, "tokens_out": None,
                          "total_in": None, "ts": ts})
        elif et == "usage":
            rec = {"tokens_in": ev.get("inputTokens"), "cached": None,
                   "tokens_out": ev.get("outputTokens"),
                   "total_in": ev.get("totalInputTokens"), "ts": ts}
            if turns and turns[-1].get("tokens_in") is None:
                turns[-1].update(rec)
            else:
                turns.append(rec)
            last_total_in = ev.get("totalInputTokens") or last_total_in
        elif et == "content_start" and ev.get("contentType") == "tool":
            name = ev.get("toolName") or ""
            calls.append({"name": name, "classes": sorted(tool_classes(name)),
                          "args": _canon_args(ev.get("input")), "ok": None, "result": None,
                          "start_rel": (ts - t0) if t0 else None, "end_rel": None,
                          "turn": max(len(turns), 1), "tokens_before": last_total_in})
            open_stack.append(calls[-1])
        elif j.get("type") == "hook_event" and j.get("hookEventName") == "tool_result" and open_stack:
            c = open_stack.pop()
            c["end_rel"] = (ts - t0) if t0 else None
    if t0 is None and not calls:
        return None
    return {"t0": t0 or 0.0, "calls": calls, "turns": turns,
            "source": "cline:--json-stream"}

# ---------- Layer 1：raw mechanical telemetry（无 oracle） ----------

def _usable_usage(turns):
    """per-turn usage 可信观测判定（usage-missing ≠ 0 修复，2026-09-12）。

    实测形态（lfl store）：tool-call assistant turn 的 usage 未持久化（记 0），
    仅末 turn 记 run 级汇总；da 通道为真实 per-turn 值；cline 无 cached。
    机械规则（通道无关，零语义猜测）：
      - tokens_in > 0          → 可信 turn：in/out/cached 取原值（None=缺失）；
      - tokens_in 为 None 或 0 → 该 turn usage 视为未持久化/不可测 → 全 None。
        首个 LLM turn 必有 prefill，0 不可能是真实观测；且无法机械证明
        provider 报告过 0，故 0 一律不作数为测得值（宁缺毋假）。
    返回 [(tokens_in|None, cached|None, tokens_out|None), ...]，与 turns 等长。
    """
    out = []
    for t in turns:
        ti = t.get("tokens_in")
        if (ti or 0) > 0:
            out.append((ti, t.get("cached"), t.get("tokens_out")))
        else:
            out.append((None, None, None))
    return out


def extract_raw(events: dict) -> dict:
    calls, turns = events.get("calls", []), events.get("turns", [])
    verif = any(c.get("ok") is not None for c in calls)   # per-call 成败可测性
    f: dict = {"source": events.get("source", ""),
               "ok_signal": verif,
               "tool_calls_declared": len(calls),
               "total_tool_calls": len(calls),
               "first_tool_name": calls[0]["name"] if calls else None,
               "first_tool_class": "|".join(sorted(calls[0]["classes"])) if calls else None,
               "first_tool_round": calls[0].get("turn") if calls else None,
               "first_tool_status": (None if not calls or calls[0].get("ok") is None
                                     else "success" if calls[0]["ok"] is True else "error"),
               # 进 calls 即有执行记录；成败不可测时 status=None（cline），可观测性由 ok_signal 表达
                "first_tool_executed": (True if calls else None),
               }
    if verif:
        f["tool_calls_executed"] = sum(1 for c in calls if c.get("ok") is not None)
        f["tool_success_count"] = sum(1 for c in calls if c.get("ok") is True)
        f["tool_failure_count_raw"] = sum(1 for c in calls if c.get("ok") is False)
    else:
        f["tool_calls_executed"] = None
        f["tool_success_count"] = None
        f["tool_failure_count_raw"] = None
    f["total_rounds"] = max((c.get("turn") or 0 for c in calls), default=0) or len(turns)
    # 首个机械有效调用（ok=True；不论工具选择对错）
    fok = next((c for c in calls if c.get("ok") is True), None)
    f["first_mechanical_valid_round"] = None
    f["time_to_first_mechanical_valid_action_s"] = None
    f["tokens_to_first_mechanical_valid_action"] = None
    if fok:
        f["first_mechanical_valid_round"] = fok.get("turn")
        if fok.get("end_rel") is not None and events.get("t0") != "":
            f["time_to_first_mechanical_valid_action_s"] = round(fok["end_rel"], 2)
        tnv = fok.get("turn")
        if tnv is not None:               # 显式 None 判定：tnv=0 不被 truthiness 吃掉
            sub = _usable_usage(turns)[:tnv]
            ins = [x for x, _, _ in sub if x is not None]
            cas = [y for _, y, _ in sub if y is not None]
            f["tokens_to_first_mechanical_valid_action"] = sum(ins) if ins else None
            f["cache_hit_tokens_to_first_mechanical_valid"] = sum(cas) if cas else None
    use = _usable_usage(turns)
    ins = [x for x, _, _ in use if x is not None]
    cas = [y for _, y, _ in use if y is not None]
    outs = [z for _, _, z in use if z is not None]
    f["input_tokens"] = sum(ins) if ins else None
    f["output_tokens"] = sum(outs) if outs else None
    f["cache_hit_tokens"] = sum(cas) if cas else None
    f["new_prefill_tokens"] = (max(f["input_tokens"] - f["cache_hit_tokens"], 0)
                               if f["input_tokens"] is not None
                               and f["cache_hit_tokens"] is not None else None)
    # usage 缺失（含 lfl store 假 0）一律 None 落盘（JSON null），不得记 0
    return f

# ---------- Layer 2：benchmark scorer（依赖 task oracle，离线） ----------

def score_fcr(raw: dict, events: dict, task: dict | None, *,
              task_effects: list[dict] | None = None,
              task_effects_status: str | None = None) -> dict:
    calls, turns = events.get("calls", []), events.get("turns", [])
    task = task or {}
    first_tools = set(task.get("first_tools") or [])
    exp_fail = task.get("expected_failures") or []
    s: dict = {}
    if calls:
        c0 = set(calls[0]["classes"])
        inter = first_tools & c0 if first_tools else set()
        if not first_tools:
            s["first_tool_selection_correct"] = None
        elif inter:
            s["first_tool_selection_correct"] = True
        elif c0 <= _LEGIT_SIDE:   # 纯 verification/搜索绕路：不判错、不计分（63-tool A/B 验证原则）
            s["first_tool_selection_correct"] = None
        else:
            s["first_tool_selection_correct"] = False
    else:
        s["first_tool_selection_correct"] = None
    s["first_call_direct"] = s["first_tool_selection_correct"]   # Directness 次指标
    if raw.get("ok_signal") and calls:
        ok0 = calls[0].get("ok")
        s["first_args_mechanically_valid"] = ok0 is True
        sel = s.get("first_tool_selection_correct")
        s["first_call_ready"] = None if sel is None else (sel and ok0 is True)
        fv = next((c for c in calls if c.get("ok") is True
                   and (not first_tools or (first_tools & set(c["classes"])))), None)
        if fv:
            s["first_task_valid_round"] = fv.get("turn")
            if fv.get("end_rel") is not None and events.get("t0") != "":
                s["time_to_first_task_valid_action_s"] = round(fv["end_rel"], 2)
            tnv = fv.get("turn")
            if tnv is not None:
                sub = _usable_usage(turns)[:tnv]
                ins = [x for x, _, _ in sub if x is not None]
                s["tokens_to_first_task_valid_action"] = sum(ins) if ins else None
        # Legacy raw-tool failure metrics remain observational. Structured task effects are
        # a separate benchmark-owned fact plane for checks whose inner process status can be
        # masked by a successful shell wrapper (T02: `python3 gen.py; echo $?`).
        repair = dup = 0
        seen_ok, failed_names = set(), set()
        legacy_exp = [e for e in exp_fail if not e.get("check_id")]
        effect_exp = [e for e in exp_fail if e.get("check_id")]
        exp_hit = unexp = unresolvable = confirmed = 0
        effect_expected = 0
        effect_unexpected = 0
        if effect_exp:
            if task_effects_status != "ok":
                unresolvable += len(effect_exp)
            else:
                pending: dict[tuple[str, str, str], int] = {}
                for effect in task_effects or []:
                    key = (str(effect.get("check_id") or ""), str(effect.get("target") or ""),
                           str(effect.get("scope") or ""))
                    code = effect.get("exit_code")
                    matching = [e for e in effect_exp if e.get("check_id") == key[0]]
                    if code == 0:
                        if pending.get(key, 0) > 0:
                            pending[key] -= 1
                            confirmed += 1
                        continue
                    if any(isinstance(e.get("exit_code"), int) and e.get("exit_code") == code
                           for e in matching):
                        effect_expected += 1
                        pending[key] = pending.get(key, 0) + 1
                    else:
                        effect_unexpected += 1
                exp_hit += effect_expected
                unexp += effect_unexpected

        # If the same structured failure is also surfaced as raw tool failure, consume at
        # most one same-class raw failure per structured expected effect so it is not double
        # counted. The expected claim itself still comes only from the structured effect.
        structured_allowance = effect_expected
        for c in calls:
            if c.get("ok") is True:
                k = (c["name"], c["args"])
                if k in seen_ok:
                    dup += 1
                else:
                    seen_ok.add(k)
                if c["name"] in failed_names:
                    repair += 1
                    failed_names.discard(c["name"])
            elif c.get("ok") is False:
                res = c.get("result") or ""
                if any((e.get("tool_class") in set(c["classes"])) and (e.get("match") in res)
                       for e in legacy_exp):
                    exp_hit += 1
                elif structured_allowance > 0 and any(
                    e.get("tool_class") in set(c["classes"]) for e in effect_exp
                ):
                    structured_allowance -= 1
                elif c.get("result_truncated"):
                    unresolvable += 1   # A05：截断且未命中 → 证据不完整，不伪造 unexpected
                else:
                    unexp += 1
                failed_names.add(c["name"])
        s["failure_to_repair_count"] = repair
        s["confirmed_repair_count"] = confirmed
        s["unnecessary_verification_count"] = dup
        s["expected_failure_count"] = exp_hit
        s["unexpected_failure_count"] = unexp
        s["expected_failure_unresolvable_count"] = unresolvable
    else:
        # cline / 未配对通道：语义成败不可测 → None，不猜
        s["first_args_mechanically_valid"] = None
        s["first_call_ready"] = None
        s["failure_to_repair_count"] = None
        s["confirmed_repair_count"] = None
        s["unnecessary_verification_count"] = None
        s["expected_failure_count"] = None
        s["unexpected_failure_count"] = None
        s["expected_failure_unresolvable_count"] = None
    return s

# ---------- 兼容组合入口（旧调用点 / 快速联查） ----------

def compute_first_call_ready(events: dict | None, first_tools=None, task: dict | None = None) -> dict | None:
    if not events:
        return None
    raw = extract_raw(events)
    t = task if task is not None else ({"first_tools": first_tools} if first_tools is not None else {})
    f = dict(raw)
    f.update(score_fcr(raw, events, t))
    return f

# ---------- runner 侧入口：返回 (raw, events)，events 随 results 落盘供 scorer 复算 ----------

def fcr_lfl(ws, sid: str):
    p = _find_lfl_session(ws, sid)
    ev = events_lfl(p) if p else None
    return (extract_raw(ev), ev) if ev else (None, None)

def fcr_da(telemetry: dict | None):
    ev = events_da(telemetry)
    return (extract_raw(ev), ev) if ev else (None, None)

def fcr_cline(stream_text: str):
    ev = events_cline(stream_text)
    return (extract_raw(ev), ev) if ev else (None, None)
