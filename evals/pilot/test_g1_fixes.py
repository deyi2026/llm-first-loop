#!/usr/bin/env python3
"""M1-G1 修复验收 fixtures（S1 三项缺陷 + S2 前半）。

运行: python3 test_g1_fixes.py   （全部 PASS 即修复生效；frozen112 回归见 analyze.py 默认数据输出）
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telemetry as tl, tasks as tk

# ---- T1a A01: 当前 tasks.py 通过启动校验
errs = tk.validate_oracles()
assert errs == [], f"should pass, got {errs}"
print("T1a PASS validate_oracles(修复后 tasks.py) = []")

# ---- T1b A01: 投毒标注(shell)被明确报出
TBI = {t["id"]: t for t in tk.TASKS}
t02 = dict(TBI["t02_retry_transient"])
t02["expected_failures"] = [{"tool_class": "shell", "match": "transient"}]
old = tk.TASKS; tk.TASKS = [t02]
errs2 = tk.validate_oracles(); tk.TASKS = old
assert errs2 and "shell" in errs2[0] and "t02" in errs2[0], errs2
print("T1b PASS 投毒报错:", errs2[0])

# ---- T2 F08: 失败标记在 200 字符之外（旧截断必丢），新保留度下正确配对
body = "x" * 300 + "transient: first run always fails"
assert "transient" not in body[:200], "fixture sanity: 旧 200 截断确实丢失标记"
tel = {"t0": "", "source": "da:adapter-stdout", "turns": [],
       "calls": [{"name": "execute_command", "args": {"command": "python3 gen.py"},
                  "ok": False, "result": body[:tl.RESULT_CAP],
                  "result_len": len(body), "result_truncated": len(body) > tl.RESULT_CAP,
                  "call_id": "call_abc", "turn": 1}]}
ev = tl.events_da(tel)
task = TBI["t02_retry_transient"]
s = tl.score_fcr({"name": "execute_command", "args": {"command": "python3 gen.py"}, "ok_signal": True}, ev, task)
assert s["expected_failure_count"] == 1, s
assert s["unexpected_failure_count"] == 0, s
assert s["expected_failure_unresolvable_count"] == 0, s
assert ev["calls"][0]["call_id"] == "call_abc"
print("T2 PASS 标记>200字符 → expected=1/unexpected=0/unresolvable=0, call_id 保留")

# ---- T3 A05: 截断且未命中 → unresolvable 而非伪造 unexpected
body3 = "y" * 2500 + "no marker"
tel3 = {"t0": "", "source": "da:x", "turns": [],
        "calls": [{"name": "execute_command", "args": {"command": "x"}, "ok": False,
                   "result": body3[:tl.RESULT_CAP], "result_len": len(body3),
                   "result_truncated": True, "call_id": "c2", "turn": 1}]}
s3 = tl.score_fcr({"name": "execute_command", "args": {"command": "x"}, "ok_signal": True}, tl.events_da(tel3), task)
assert s3["expected_failure_unresolvable_count"] == 1, s3
assert s3["unexpected_failure_count"] == 0, s3
print("T3 PASS 截断+未命中 → unresolvable=1/unexpected=0")

# ---- T4 S2/t12: analyze._scored 读 resume_fcr_events
import analyze as az, json
row = {"agent": "lfl", "run": 1, "task": "t02_retry_transient", "status": "PASS",
       "first_call": None, "resume_first_call": {"name": "execute_command", "args": {"command": "python3 gen.py"}, "ok_signal": True},
       "resume_fcr_events": tl.events_da(tel)}
sc = az._scored(row)
assert sc["expected_failure_count"] == 1, sc
print("T4 PASS _scored 经 resume_fcr_events 复算 expected=1")
print("ALL G1 FIXTURE TESTS PASS")
