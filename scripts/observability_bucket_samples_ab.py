#!/usr/bin/env python3
# 可观测性桶样本驱动（2026-10-14 战役用）：A interruptible / B llm_stream_interrupt / C final_gate 竞速。用法见 docs/ANALYSIS-20261014-observability-m0-findings.md §9
"""看板真实样本补全驱动 v2：修正 SSE 单行 data 信封与 session 发现。"""

import json
import threading
import time

import requests

BASE = "http://127.0.0.1:8903"
MODEL = "glm/glm-5.3-flash"
OUT = "reports/observability-real-samples"
TAG = time.strftime("%Y%m%d-%H%M%S") + "v3"
log = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": MODEL, "scenarios": []}


def jget(path):
    r = requests.get(BASE + path, timeout=15)
    r.raise_for_status()
    return r.json()


def jpost(path, body):
    r = requests.post(BASE + path, json=body, timeout=15)
    r.raise_for_status()
    return r.json()


class SSE:
    def __init__(self, payload):
        self.payload_holder = payload
        self.session_id = None
        self.run_generation = None
        self.deltas = 0
        self.reasoning = 0
        self.tool_round_events = []
        self.tool_result_events = []
        self.done = False
        self.done_payload = None
        self.err = None
        self.last_delta_t = None
        self.last_tool_round_t = None
        self.started = time.monotonic()
        self._stop = threading.Event()
        self.events = []
        self.thread = threading.Thread(target=self._run, daemon=True)
        # 线程在构造末尾启动，payload 已就位
        self.thread.start()

    def _run(self):
        try:
            with requests.post(
                BASE + "/api/v1/chat/stream",
                json=self.payload_holder,
                stream=True,
                timeout=(15, 900),
            ) as r:
                if r.status_code != 200:
                    self.err = f"http {r.status_code}: {r.text[:300]}"
                    self.done = True
                    return
                for raw in r.iter_lines(decode_unicode=True):
                    if self._stop.is_set():
                        break
                    if not raw:
                        continue
                    line = raw.strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        msg = json.loads(line.split(":", 1)[1].strip())
                    except Exception:
                        continue
                    t = msg.get("type")
                    d = msg.get("data") or {}
                    now = time.monotonic()
                    self.events.append((round(now - self.started, 3), t))
                    if t == "run_started":
                        self.session_id = d.get("session_id")
                        self.run_generation = d.get("run_generation")
                    elif t == "answer_delta":
                        self.deltas += 1
                        self.last_delta_t = now
                    elif t == "reasoning_delta":
                        self.reasoning += 1
                    elif t == "tool_round":
                        self.last_tool_round_t = now
                        self.tool_round_events.append(d)
                    elif t == "tool_result":
                        self.tool_result_events.append(d)
                    elif t == "done":
                        self.done = True
                        self.done_payload = d
                        break
                    elif t == "error":
                        self.done = True
                        self.done_payload = {"error": d}
                        break
        except Exception as e:
            self.err = f"{type(e).__name__}: {e}"[:300]
            self.done = True

    def stop(self):
        self._stop.set()


def run_scenario(name, message, trigger, probe_msg, max_wait_run=300):
    rec = {"name": name, "message": message[:140]}
    sse = SSE({"new_session": True, "model": MODEL, "message": message})
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30 and not sse.session_id and not sse.err:
        time.sleep(0.3)
    sid = sse.session_id
    rec["session_id"] = sid
    rec["sse_err"] = sse.err
    if not sid:
        rec["error"] = "no session_id from run_started"
        log["scenarios"].append(rec)
        with open(f"{OUT}/DRIVER_{TAG}.json", "w") as fh:
            json.dump(log, fh, ensure_ascii=False, indent=1)
        print(f"[{name}] FAIL: {sse.err}", flush=True)
        time.sleep(2)
        return rec
    t1 = time.monotonic()
    while time.monotonic() - t1 < 180 and not sse.done:
        if trigger(sse):
            break
        time.sleep(0.2)
    rec["trigger_wait_s"] = round(time.monotonic() - t1, 2)
    rec["state_at_trigger"] = {
        "deltas": sse.deltas,
        "reasoning": sse.reasoning,
        "tool_rounds": len(sse.tool_round_events),
        "tool_round_names": [e.get("tool_name") for e in sse.tool_round_events],
    }
    q = jpost("/api/v1/chat/queue", {"session_id": sid, "message": probe_msg})
    qid = q.get("queue_id")
    rec["enqueue"] = {"queue_id": qid, "position": q.get("position")}
    try:
        ij = jpost(
            "/api/v1/chat/queue/interject",
            {"session_id": sid, "queue_id": qid, "run_generation": sse.run_generation or ""},
        )
        rec["interject"] = {"state": ij.get("state"), "grade": ij.get("grade")}
    except requests.HTTPError as e:
        rec["interject"] = {"http_error": e.response.status_code, "body": e.response.text[:200]}
    except Exception as e:
        rec["interject"] = {"error": str(e)[:150]}
    t2 = time.monotonic()
    while time.monotonic() - t2 < max_wait_run and not sse.done:
        time.sleep(1)
    rec["run_done"] = sse.done
    ans = (sse.done_payload or {}).get("answer") if isinstance(sse.done_payload, dict) else None
    rec["answer_snip"] = str(ans)[:150]
    sse.stop()
    snap = {}
    t3 = time.monotonic()
    while time.monotonic() - t3 < 90:
        try:
            it = jget(f"/api/v1/chat/queue/item?session_id={sid}&queue_id={qid}")
            snap = it.get("item", it)
            st = snap.get("status")
            if st in ("consumed", "completed", "failed", "cancelled", "denied", "requeued"):
                break
        except Exception as e:
            snap = {"poll_error": str(e)[:120]}
        time.sleep(2)
    rec["queue_terminal"] = {
        k: snap.get(k)
        for k in (
            "status",
            "consumed_via",
            "interrupt_receipt",
            "interject_requested_at",
            "received_at",
            "applied_at",
        )
        if k in snap
    }
    try:
        rec["session_metrics"] = jget(f"/api/v1/chat/queue/metrics?session_id={sid}")
    except Exception as e:
        rec["session_metrics"] = {"error": str(e)[:120]}
    log["scenarios"].append(rec)
    with open(f"{OUT}/DRIVER_{TAG}.json", "w") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1)
    qt = rec.get("queue_terminal", {})
    print(
        f"[{name}] via={qt.get('consumed_via')} receipt={qt.get('interrupt_receipt')} "
        f"status={qt.get('status')} deltas={rec['state_at_trigger']['deltas']} "
        f"tool_rounds={rec['state_at_trigger']['tool_rounds']}",
        flush=True,
    )
    time.sleep(2)
    return rec


def trigger_a(s):  # execute_command 派发 3s 后（sleep 25 执行中）
    return bool(s.last_tool_round_t) and time.monotonic() - s.last_tool_round_t > 3.0


def trigger_b(s):  # 答案流中
    return s.deltas >= 12


def trigger_c(s):  # 流尾停顿 ≥0.8s（且已有足量增量）
    if s.deltas < 25 or s.done:
        return False
    return time.monotonic() - (s.last_delta_t or 0) > 0.8


g0 = jget("/api/v1/chat/queue/metrics/global")
log["global_before"] = g0
print(
    "BEFORE:",
    json.dumps({k: v.get("n") for k, v in g0.get("buckets", {}).items()}, ensure_ascii=False),
    flush=True,
)

run_scenario(
    "A_interruptible",
    "请立即使用 execute_command 工具前台执行命令：sleep 25 && echo LFL_SAMPLE_DONE 。"
    "等待完成后把 stdout 原样告诉我。不要后台运行，不要做其它事。",
    trigger_a,
    "【看板样本·插话A】请中止当前等待，直接回复：收到插话A。",
)
run_scenario(
    "B_stream_interrupt",
    "请写一篇约 1500 字的说明文，主题：可观测性为什么对 Agent 系统重要。直接输出全文，不要调用任何工具。",
    trigger_b,
    "【看板样本·插话B】请停止继续写，直接回复：收到插话B。",
)
run_scenario(
    "C_stream_tail",
    "请写一篇约 2000 字的综述，主题：时间敏感系统的时延度量方法。直接输出全文，不要调用任何工具。",
    trigger_c,
    "【看板样本·插话C】收到请直接回复：收到插话C。",
)

g1 = jget("/api/v1/chat/queue/metrics/global")
log["global_after"] = g1
with open(f"{OUT}/GLOBAL_METRICS_{TAG}.json", "w") as fh:
    json.dump(g1, fh, ensure_ascii=False, indent=1)
with open(f"{OUT}/DRIVER_{TAG}.json", "w") as fh:
    json.dump(log, fh, ensure_ascii=False, indent=1)
print(
    "AFTER:",
    json.dumps({k: v.get("n") for k, v in g1.get("buckets", {}).items()}, ensure_ascii=False),
    flush=True,
)
print("ALL_DONE", flush=True)
