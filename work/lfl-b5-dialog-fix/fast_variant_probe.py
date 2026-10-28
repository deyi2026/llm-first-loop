"""300ms auto-dialog variant: NO deliberate observation before the dialog.
Question: can browser_operate do=dialog still handle it? (The navigate verb's
own pre-capture may have persisted an about:blank world to ground against.)"""
import json, sys, threading, time, functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

srv = ThreadingHTTPServer(("127.0.0.1", 8799), functools.partial(SimpleHTTPRequestHandler, directory="work/lfl-b5-dialog-fix/pages"))
threading.Thread(target=srv.serve_forever, daemon=True).start()
sys.path.insert(0, "work/lfl-b5-dialog-fix")
from live_b5_fix_check import Stack, new_target, close_target, find_mirror, OUT

out = {}
tid = new_target()
try:
    s = Stack(tid, OUT / "fast")
    t0 = time.monotonic()
    nav = s.operate_raw(do="navigate", url=f"http://127.0.0.1:8799/dialog_fast.html?run={int(time.time())}")
    out["navigate"] = {"status": nav.get("status"), "elapsed_s": round(time.monotonic() - t0, 1)}
    time.sleep(1.5)  # the 300ms dialog has long fired; no observation was ever taken
    out["dialog_open_before"] = s.actuator._dialog_open
    out["latest_world"] = s.perception.latest_world_version("live-b5-fix")
    t0 = time.monotonic()
    acc = s.operate_raw(do="dialog", action="accept")
    out["dialog_accept"] = {
        "status": acc.get("status"),
        "elapsed_s": round(time.monotonic() - t0, 1),
        "halt_reason": acc.get("halt_reason"),
    }
    time.sleep(0.4)
    snap = s.snapshot()
    out["t1_after"] = find_mirror(snap, "t1")
    out["capture_after_ok"] = bool(s.host.capture())
finally:
    close_target(tid)
    srv.shutdown()
print(json.dumps(out, ensure_ascii=False, indent=1))
