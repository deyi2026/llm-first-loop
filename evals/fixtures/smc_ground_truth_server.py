"""Shared loopback ground-truth fixture for SMC browser qualifications.

Delta vs the per-eval ``fixture_server.py`` copies (``evals/browser_smc_*``):

* one server, many routes (a route table) instead of one task_id page;
* ``/manifest`` exposes the expected canonical objects per route as data,
  so qualification runners can mechanically assert "hit the expected node"
  instead of hardcoding DOM expectations;
* dedicated pages for the two FC2-B failure modes: name pollution
  (actionable button + same-name StaticText child) and same ``kind + name``
  ambiguity (two identical buttons -> contract-mandated halt, zero effect);
* scroll and multi-page navigate coverage (absent from existing copies);
* query-parametrized delays (``?delay_ms=``) for typed-wait matrices;
* one route carrying ``hx-*`` attributes (with a no-CDN behavior shim) as
  the observation hook for any future HTMX-grounding comparison.

Zero third-party dependencies. Loopback 127.0.0.1, ephemeral port, context
manager. Never import this from production code.

Run the self-check:  python3 evals/fixtures/smc_ground_truth_server.py
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

FIXTURE_ID = "smc_ground_truth_server.v1"

# ---------------------------------------------------------------------------
# shared page pieces
# ---------------------------------------------------------------------------

_EMIT_JS_TEMPLATE = """
<script>
const ROUTE={route_json};
async function emit(payload){{
  payload.route=ROUTE;
  const r=await fetch('/event',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});
  const out=await r.json();
  const el=document.getElementById('receipt');
  if(el){{el.textContent=out.ok?'Submitted':'Rejected';}}
}}
</script>
"""


def _shell(title: str, route: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head>"
        f"<body data-fixture-route='{route}'>{body}"
        + _EMIT_JS_TEMPLATE.format(route_json=json.dumps(route))
        + "</body></html>"
    )


def _receipt_div() -> str:
    return "<div id=\"receipt\" aria-label=\"Submission status\">Not submitted</div>"


def _delay_ms(query: dict[str, list[str]], default: int = 900) -> int:
    raw = query.get("delay_ms", [str(default)])[0]
    try:
        return min(max(int(raw), 0), 60_000)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# page builders: (route, query) -> html
# ---------------------------------------------------------------------------


def _page_index(route: str, _query: dict[str, list[str]]) -> str:
    links = "".join(f"<li><a href='{r}'>{r}</a></li>" for r in sorted(PAGE_ROUTES) if r != "/")
    return _shell("SMC ground truth index", route, f"<h1>SMC ground truth fixture index</h1><ul>{links}</ul>")


def _page_unique_click(route: str, _query: dict[str, list[str]]) -> str:
    body = (
        "<h1>Unique click task</h1>"
        "<button id='run-check' aria-label='Run check'>Run check</button>"
        "<script>document.getElementById('run-check').addEventListener('click',"
        "()=>emit({kind:'click',element_id:'run-check'}));</script>"
        + _receipt_div()
    )
    return _shell("Unique click", route, body)


def _page_unique_fill(route: str, _query: dict[str, list[str]]) -> str:
    body = (
        "<h1>Project code task</h1>"
        "<label>Project code <input id='code' aria-label='Project code' value=''></label>"
        "<button id='save' aria-label='Save code'>Save code</button>"
        "<script>document.getElementById('save').addEventListener('click',"
        "()=>emit({kind:'fill',element_id:'code',value:document.getElementById('code').value}));</script>"
        + _receipt_div()
    )
    return _shell("Unique fill", route, body)


def _page_unique_select(route: str, _query: dict[str, list[str]]) -> str:
    body = (
        "<h1>Region task</h1>"
        "<label>Region <select id='region' aria-label='Region'>"
        "<option value='east'>East</option><option value='west'>West</option></select></label>"
        "<button id='save-region' aria-label='Save region'>Save region</button>"
        "<script>document.getElementById('save-region').addEventListener('click',"
        "()=>emit({kind:'select',element_id:'region',value:document.getElementById('region').value}));</script>"
        + _receipt_div()
    )
    return _shell("Unique select", route, body)


def _page_unique_scroll(route: str, _query: dict[str, list[str]]) -> str:
    items = "".join(f"<p id='item-{i}'>Item {i}</p>" for i in range(1, 41))
    body = (
        "<h1>Scroll task</h1>"
        "<div id='scroll-area' role='region' aria-label='Scroll area' "
        "style='height:200px;overflow:auto;border:1px solid #999;padding:4px'>" + items + "</div>"
        "<script>const area=document.getElementById('scroll-area');let t=null;"
        "area.addEventListener('scroll',()=>{clearTimeout(t);t=setTimeout(()=>emit({kind:'scroll',"
        "element_id:'scroll-area',scrollTop:Math.round(area.scrollTop)}),120);});</script>"
        + _receipt_div()
    )
    return _shell("Unique scroll", route, body)


def _page_pollution(route: str, _query: dict[str, list[str]]) -> str:
    # FC2-B live probe: Chrome AX exposes the actionable button PLUS same-name
    # StaticText/InlineTextBox children. name-only matching sees >=2 objects;
    # kind=button + name resolves to exactly the button.
    body = (
        "<h1>Name pollution task</h1>"
        "<button id='commit' aria-label='Commit choice'><span>Commit choice</span></button>"
        "<script>document.getElementById('commit').addEventListener('click',"
        "()=>emit({kind:'click',element_id:'commit'}));</script>"
        + _receipt_div()
    )
    return _shell("Name pollution", route, body)


def _page_ambiguous(route: str, _query: dict[str, list[str]]) -> str:
    # Two same kind+name buttons. The contract MUST halt with a mechanical
    # receipt and zero side effect; the /state event log must stay empty.
    body = (
        "<h1>Ambiguous deploy task</h1>"
        "<p>Slot A</p><button id='deploy-a' aria-label='Deploy'>Deploy</button>"
        "<p>Slot B</p><button id='deploy-b' aria-label='Deploy'>Deploy</button>"
        "<script>['deploy-a','deploy-b'].forEach(id=>document.getElementById(id)"
        ".addEventListener('click',()=>emit({kind:'click',element_id:id})));</script>"
        + _receipt_div()
    )
    return _shell("Ambiguous deploy", route, body)


def _page_wait_enable(route: str, query: dict[str, list[str]]) -> str:
    delay = _delay_ms(query)
    body = (
        "<h1>Delayed readiness task</h1>"
        "<div id='status' aria-label='Readiness status'>Waiting</div>"
        "<button id='run-check' aria-label='Run check' disabled>Run check</button>"
        "<script>const b=document.getElementById('run-check');"
        "b.addEventListener('click',()=>emit({kind:b.disabled?'early_click':'ready_click',element_id:'run-check'}));"
        f"setTimeout(()=>{{document.getElementById('status').textContent='Ready';b.disabled=false;}},{delay});</script>"
        + _receipt_div()
    )
    return _shell("Delayed enable", route, body)


def _page_wait_appear(route: str, query: dict[str, list[str]]) -> str:
    delay = _delay_ms(query)
    body = (
        "<h1>Delayed appear task</h1>"
        "<div id='anchor' aria-label='Pending anchor'>Pending</div>"
        "<script>"
        f"setTimeout(()=>{{const d=document.createElement('div');d.id='target';"
        "d.setAttribute('aria-label','Result panel');d.textContent='Result ready';"
        "document.getElementById('anchor').after(d);}," + str(delay) + ");</script>"
        + _receipt_div()
    )
    return _shell("Delayed appear", route, body)


def _page_nav_a(route: str, _query: dict[str, list[str]]) -> str:
    body = "<h1>Ground truth page A</h1><p data-page='a'>Resource A</p><a href='/navigate/page-b'>Go to page B</a>"
    return _shell("Ground truth page A", route, body)


def _page_nav_b(route: str, _query: dict[str, list[str]]) -> str:
    body = "<h1>Ground truth page B</h1><p data-page='b'>Resource B</p><a href='/navigate/page-a'>Go to page A</a>"
    return _shell("Ground truth page B", route, body)


def _page_htmx(route: str, _query: dict[str, list[str]]) -> str:
    # hx-* attributes present in the DOM as the observation hook for any
    # future HTMX-grounding comparison. Behavior is a local fetch shim, so
    # no CDN/network dependency.
    body = (
        "<h1>HTMX attribute task</h1>"
        "<button id='hx-commit' aria-label='Hx commit' hx-post='/event' hx-target='#receipt' hx-swap='innerHTML'>"
        "Hx commit</button>"
        "<script>document.querySelectorAll('[hx-post]').forEach(el=>{el.addEventListener('click',async()=>{"
        "const target=document.querySelector(el.getAttribute('hx-target'));"
        "const r=await fetch(el.getAttribute('hx-post'),{method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({kind:'hx_click',element_id:el.id})});"
        "target.textContent=r.ok?'Hx submitted':'Hx rejected';});});</script>"
        + _receipt_div()
    )
    return _shell("HTMX attribute", route, body)


# ---------------------------------------------------------------------------
# route table + manifest (single source of truth)
# ---------------------------------------------------------------------------

PAGE_ROUTES: dict[str, dict[str, Any]] = {
    "/": {
        "builder": _page_index,
        "manifest": {
            "title": "index",
            "marker": "SMC ground truth fixture index",
            "canonical_objects": [],
            "contract_notes": "navigate target with route links",
        },
    },
    "/unique/click": {
        "builder": _page_unique_click,
        "manifest": {
            "title": "unique click",
            "marker": "id='run-check'",
            "canonical_objects": [
                {"kind": "button", "name": "Run check", "expected_id": "run-check", "kind_name_matches": 1}
            ],
            "expected_events": [{"kind": "click", "element_id": "run-check", "count": 1}],
            "contract_notes": "exact-unique identity dispatches exactly once",
        },
    },
    "/unique/fill": {
        "builder": _page_unique_fill,
        "manifest": {
            "title": "unique fill",
            "marker": "id='code'",
            "canonical_objects": [
                {"kind": "input", "name": "Project code", "expected_id": "code", "kind_name_matches": 1},
                {"kind": "button", "name": "Save code", "expected_id": "save", "kind_name_matches": 1},
            ],
            "expected_events": [{"kind": "fill", "element_id": "code", "count": 1}],
            "contract_notes": "canonical FC2-C names; fill then confirm via Save code",
        },
    },
    "/unique/select": {
        "builder": _page_unique_select,
        "manifest": {
            "title": "unique select",
            "marker": "id='region'",
            "canonical_objects": [
                {"kind": "select", "name": "Region", "expected_id": "region", "kind_name_matches": 1,
                 "note": "canonical kind for <select> not pinned by FC2-B doc; grounded by role"}
            ],
            "expected_events": [{"kind": "select", "element_id": "region", "count": 1}],
            "contract_notes": "native <select>; option values east/west",
        },
    },
    "/unique/scroll": {
        "builder": _page_unique_scroll,
        "manifest": {
            "title": "unique scroll",
            "marker": "id='scroll-area'",
            "canonical_objects": [
                {"kind": "region", "name": "Scroll area", "expected_id": "scroll-area", "kind_name_matches": 1,
                 "note": "scroll container; canonical kind not pinned by FC2-B doc"}
            ],
            "expected_events": [{"kind": "scroll", "element_id": "scroll-area", "count": ">=1"}],
            "contract_notes": "40 numbered items; scroll events debounced 120ms",
        },
    },
    "/pollution/button-text-child": {
        "builder": _page_pollution,
        "manifest": {
            "title": "name pollution",
            "marker": "id='commit'",
            "canonical_objects": [
                {"kind": "button", "name": "Commit choice", "expected_id": "commit", "kind_name_matches": 1,
                 "name_only_matches": ">=2"}
            ],
            "expected_events": [{"kind": "click", "element_id": "commit", "count": 1}],
            "contract_notes": "FC2-B live-probe phenomenon: button + same-name StaticText child; "
                              "name-only matching is polluted, kind+name resolves exactly",
        },
    },
    "/ambiguous/two-buttons": {
        "builder": _page_ambiguous,
        "manifest": {
            "title": "ambiguous deploy",
            "marker": "id='deploy-a'",
            "canonical_objects": [
                {"kind": "button", "name": "Deploy", "expected_id": None, "kind_name_matches": 2}
            ],
            "expected_events": [],
            "contract_notes": "same kind+name twice -> contract MUST halt with mechanical receipt, "
                              "zero side effect, /state stays empty",
        },
    },
    "/wait/delayed-enable": {
        "builder": _page_wait_enable,
        "manifest": {
            "title": "delayed enable",
            "marker": "id='run-check'",
            "canonical_objects": [
                {"kind": "button", "name": "Run check", "expected_id": "run-check", "kind_name_matches": 1}
            ],
            "expected_events": [{"kind": "ready_click", "element_id": "run-check", "count": 1}],
            "contract_notes": "?delay_ms= (default 900, clamp 0..60000); typed wait property=enabled "
                              "must precede the single mutation; early_click events are failures",
        },
    },
    "/wait/delayed-appear": {
        "builder": _page_wait_appear,
        "manifest": {
            "title": "delayed appear",
            "marker": "id='anchor'",
            "canonical_objects": [
                {"kind": "div", "name": "Result panel", "expected_id": "target", "kind_name_matches": 1,
                 "note": "appears after delay_ms; canonical kind not pinned by FC2-B doc"}
            ],
            "expected_events": [],
            "contract_notes": "?delay_ms=; typed wait predicate=visible on an object that does not "
                              "exist at load; page has no mutation target",
        },
    },
    "/navigate/page-a": {
        "builder": _page_nav_a,
        "manifest": {
            "title": "page A",
            "marker": "data-page='a'",
            "canonical_objects": [],
            "contract_notes": "distinct page resource for the navigate clause",
        },
    },
    "/navigate/page-b": {
        "builder": _page_nav_b,
        "manifest": {
            "title": "page B",
            "marker": "data-page='b'",
            "canonical_objects": [],
            "contract_notes": "distinct page resource for the navigate clause",
        },
    },
    "/htmx/click": {
        "builder": _page_htmx,
        "manifest": {
            "title": "htmx attribute",
            "marker": "hx-post='/event'",
            "canonical_objects": [
                {"kind": "button", "name": "Hx commit", "expected_id": "hx-commit", "kind_name_matches": 1,
                 "attributes": ["hx-post", "hx-target", "hx-swap"]}
            ],
            "expected_events": [{"kind": "hx_click", "element_id": "hx-commit", "count": 1}],
            "contract_notes": "observation hook only: hx-* attributes are present in the DOM; behavior "
                              "is a local fetch shim (no htmx.js, no CDN, loopback only)",
        },
    },
}


def build_manifest() -> dict[str, Any]:
    return {
        "fixture": FIXTURE_ID,
        "notes": "expected canonical objects per route; kind_name_matches is the count the strict "
                 "kind+name grounding must see; name_only_matches documents pollution",
        "routes": {path: entry["manifest"] for path, entry in PAGE_ROUTES.items()},
    }


# ---------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------

_ALLOWED_EVENT_KEYS = {"kind", "element_id", "value", "scrollTop", "phase"}


class FixtureState:
    """Thread-safe append-only event log: the server-side ground truth."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = {key: payload[key] for key in _ALLOWED_EVENT_KEYS if key in payload}
        with self._lock:
            event["seq"] = len(self._events) + 1
            event["server_ts"] = round(time.time(), 3)
            self._events.append(event)
            return dict(event)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"fixture": FIXTURE_ID, "count": len(self._events),
                    "events": [dict(item) for item in self._events]}


class GroundTruthServer:
    def __init__(self) -> None:
        self.state = FixtureState()
        state = self.state
        manifest_raw = json.dumps(build_manifest(), sort_keys=True).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                if path == "/manifest":
                    self._send(200, manifest_raw, "application/json")
                    return
                if path == "/state":
                    raw = json.dumps(state.snapshot(), sort_keys=True).encode("utf-8")
                    self._send(200, raw, "application/json")
                    return
                entry = PAGE_ROUTES.get(path)
                if entry is None:
                    self._send(404, b"not found", "text/plain")
                    return
                html = entry["builder"](path, query).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/event":
                    self._send(404, b'{"ok":false}', "application/json")
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(payload, dict):
                        raise ValueError("payload must be object")
                    state.record(payload)
                    self._send(200, b'{"ok":true}', "application/json")
                except (ValueError, json.JSONDecodeError):
                    self._send(400, b'{"ok":false}', "application/json")

            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ARG002
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/"

    def route_url(self, path: str, **params: Any) -> str:
        base = self.url.rstrip("/") + path
        if params:
            from urllib.parse import urlencode
            base += "?" + urlencode(params)
        return base

    def __enter__(self) -> GroundTruthServer:
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# self-check: python3 evals/fixtures/smc_ground_truth_server.py
# ---------------------------------------------------------------------------


def _self_check() -> int:
    import urllib.request

    failures: list[str] = []
    with GroundTruthServer() as srv:
        base = srv.url
        with urllib.request.urlopen(base + "manifest", timeout=5) as resp:
            manifest = json.loads(resp.read().decode("utf-8"))
        assert manifest["fixture"] == FIXTURE_ID
        for path, meta in manifest["routes"].items():
            with urllib.request.urlopen(base.rstrip("/") + path + "?delay_ms=50", timeout=5) as resp:
                body = resp.read().decode("utf-8")
                marker = meta.get("marker")
                if marker and marker not in body:
                    failures.append(f"{path}: marker missing: {marker}")
                if "data-fixture-route='{}'".format(path) not in body:
                    failures.append(f"{path}: route stamp missing")
        req = urllib.request.Request(
            base + "event", data=json.dumps({"kind": "click", "element_id": "selfcheck"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if json.loads(resp.read().decode()) != {"ok": True}:
                failures.append("event POST not ok")
        with urllib.request.urlopen(base + "state", timeout=5) as resp:
            state = json.loads(resp.read().decode())
        if state["count"] != 1 or state["events"][0]["element_id"] != "selfcheck":
            failures.append("state log wrong: " + json.dumps(state))
    if failures:
        print("SELF-CHECK FAIL:")
        for item in failures:
            print(" -", item)
        return 1
    print(f"SELF-CHECK PASS: {len(manifest['routes'])} routes, markers ok, event log ok, port ephemeral")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_check())
