import time
from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall
from tests.phase4.test_m0_scenarios import _wait_tool_started, INTERJECT_TEXT

def test_dbg(build_test_engine):
    engine, fake = build_test_engine([
        {"content": "go", "tool_calls": [ToolCall(id="d1", name="execute_command", arguments={"command": "sleep 0.3"})]},
        {"content": "f1"},
        {"content": "go2", "tool_calls": [ToolCall(id="d2", name="execute_command", arguments={"command": "sleep 0.3"})]},
        {"content": "f2"},
    ])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    _h, q = runner.start(sid, "r1")
    assert _wait_tool_started(engine, "execute_command", "_active_procs")
    import queue as _q
    while True:
        try:
            e = q.get(timeout=10)
        except _q.Empty:
            break
        if e.get("type") in ("done", "error"):
            print("[dbg] run1 final:", e.get("type"), str(e.get("error"))[:200], flush=True)
            break
    time.sleep(0.2)
    print("[dbg] run1 llm calls:", len(fake.calls), flush=True)
    h = runner.get_handle(sid)
    print("[dbg] handle after r1:", (h or {}).get("status"), flush=True)
    try:
        _h2, q2 = runner.start(sid, "r2")
        print("[dbg] run2 started ok", flush=True)
    except Exception as ex:
        print("[dbg] run2 start raise:", ex, flush=True)
        return
    import queue as _q2
    events = []
    try:
        while True:
            events.append(q2.get(timeout=6))
    except _q2.Empty:
        pass
    for e in events:
        print("[dbg] r2 ev:", e.get("type"), str(e.get("error"))[:300], flush=True)
    print("[dbg] total llm calls:", len(fake.calls), flush=True)
