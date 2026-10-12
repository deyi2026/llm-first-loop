"""Loopback-only deterministic Browser fixtures for real-model A/B."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _page(task_id: str) -> str:
    common = """
<script>
async function emit(payload) {
  const r = await fetch('/event', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const out = await r.json();
  document.getElementById('receipt').textContent = out.ok ? 'Submitted' : 'Rejected';
}
</script>
<div id="receipt" aria-label="Submission status">Not submitted</div>
"""
    if task_id == "click_commit":
        body = """
<h1>Commit task</h1>
<button id="commit" aria-label="Commit choice">Commit choice</button>
<script>document.getElementById('commit').addEventListener('click', () => emit({kind:'commit'}));</script>
"""
    elif task_id == "fill_submit":
        body = """
<h1>Project code task</h1>
<label>Project code <input id="code" aria-label="Project code" value=""></label>
<button id="save" aria-label="Save code">Save code</button>
<script>document.getElementById('save').addEventListener('click', () => emit({kind:'save_code', value:document.getElementById('code').value}));</script>
"""
    elif task_id == "delayed_wait":
        body = """
<h1>Delayed readiness task</h1>
<div id="status" aria-label="Readiness status">Waiting</div>
<button id="finalize" aria-label="Finalize after ready" disabled>Finalize after ready</button>
<script>
const b=document.getElementById('finalize');
b.addEventListener('click', () => emit({kind:b.disabled?'early_click':'ready_click'}));
setTimeout(() => { document.getElementById('status').textContent='Ready'; b.disabled=false; }, 900);
</script>
"""
    elif task_id == "select_submit":
        body = """
<h1>Region task</h1>
<label>Region <select id="region" aria-label="Region"><option value="east">East</option><option value="west">West</option></select></label>
<button id="save-region" aria-label="Save region">Save region</button>
<script>document.getElementById('save-region').addEventListener('click', () => emit({kind:'save_region', value:document.getElementById('region').value}));</script>
"""
    elif task_id == "replacement_click":
        body = """
<h1>Replacement identity task</h1>
<div id="version" aria-label="Deploy version">Version 1</div>
<button id="deploy-v1" aria-label="Deploy">Deploy</button>
<script>
document.getElementById('deploy-v1').addEventListener('click', () => emit({kind:'deploy', generation:1}));
setTimeout(() => {
  const old=document.getElementById('deploy-v1');
  const next=document.createElement('button'); next.id='deploy-v2'; next.setAttribute('aria-label','Deploy'); next.textContent='Deploy';
  next.addEventListener('click', () => emit({kind:'deploy', generation:2}));
  old.replaceWith(next); document.getElementById('version').textContent='Version 2';
}, 900);
</script>
"""
    else:
        raise KeyError(task_id)
    return "<!doctype html><html><head><meta charset='utf-8'><title>Browser A/B Fixture</title></head><body>" + body + common + "</body></html>"


class FixtureState:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, payload: dict[str, Any]) -> None:
        allowed = {"kind", "value", "generation"}
        event = {key: payload[key] for key in allowed if key in payload}
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"task_id": self.task_id, "events": [dict(item) for item in self._events]}


class FixtureServer:
    def __init__(self, task_id: str) -> None:
        self.state = FixtureState(task_id)
        state = self.state
        page = _page(task_id).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/state":
                    raw = json.dumps(state.snapshot(), sort_keys=True).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                elif self.path == "/":
                    raw = page
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                else:
                    self.send_response(404)
                    raw = b"not found"
                    self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/event":
                    self.send_response(404)
                    self.end_headers()
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(payload, dict):
                        raise ValueError("payload must be object")
                    state.record(payload)
                    raw = b'{"ok":true}'
                    self.send_response(200)
                except (ValueError, json.JSONDecodeError):
                    raw = b'{"ok":false}'
                    self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ARG002
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/"

    def __enter__(self) -> FixtureServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)
