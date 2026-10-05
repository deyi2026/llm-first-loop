#!/usr/bin/env python3
"""S0 spike probe (DESIGN-20261005 v4 SS5, G2): attestation mechanism facts.

Per invocation launches ONE throwaway Chrome (dedicated temp user-data-dir,
about:blank only) and mechanically records:

  1. /json/version browser facts + browser-level webSocketDebuggerUrl UUID
  2. Browser.getBrowserCommandLine over a short-lived browser-level ws
     (expected: ServerError without --enable-automation per Chromium trunk
      content/browser/devtools/protocol/browser_handler.cc:676-695)
  3. navigator.webdriver via page-target ws Runtime.evaluate (flag side-effect)
  4. host-side attestation path: lsof -Fp -> PID -> ps -ww -o command= argv
  5. timings for the attestation-equivalent calls

Usage:
  s0_browser_attestation_probe.py --enable-automation [--headless] [--port N]
Prints one JSON object (probe facts). Exit 0 = probe ran; 2 = Chrome failed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import httpx
from websockets.sync.client import connect as ws_connect

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def http_get_json(url: str, timeout: float = 3.0):
    with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def wait_for_endpoint(url: str, deadline_s: float = 20.0) -> None:
    started = time.monotonic()
    while time.monotonic() - started < deadline_s:
        try:
            http_get_json(url, timeout=1.0)
            return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError(f"Chrome debug endpoint never came up: {url}")


def cdp_call(ws_url: str, method: str, params: dict | None = None, timeout_s: float = 10.0):
    """One-shot CDP command on a fresh short-lived ws connection."""
    started = time.monotonic()
    ws = ws_connect(ws_url, open_timeout=5.0, max_size=1 << 20)
    try:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            raw = ws.recv(timeout=timeout_s)
            msg = json.loads(raw)
            if isinstance(msg, dict) and msg.get("id") == 1:
                elapsed_ms = round((time.monotonic() - started) * 1000.0, 1)
                if "error" in msg:
                    return {"ok": False, "error": msg["error"], "elapsed_ms": elapsed_ms}
                return {"ok": True, "result": msg.get("result"), "elapsed_ms": elapsed_ms}
    finally:
        ws.close()


def host_side_attestation(port: int) -> dict:
    started = time.monotonic()
    out = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
        capture_output=True, text=True, timeout=5,
    )
    pids = [ln[1:].strip() for ln in out.stdout.splitlines() if ln.startswith("p")]
    lsof_ms = round((time.monotonic() - started) * 1000.0, 1)
    entry = {"lsof_exit": out.returncode, "listen_pids": pids, "lsof_ms": lsof_ms}
    if not pids:
        entry["ps_command"] = None
        return entry
    pid = pids[0]
    started = time.monotonic()
    ps = subprocess.run(
        ["ps", "-ww", "-o", "command=", "-p", pid],
        capture_output=True, text=True, timeout=5,
    )
    entry["ps_ms"] = round((time.monotonic() - started) * 1000.0, 1)
    entry["ps_exit"] = ps.returncode
    cmd = ps.stdout.strip()
    entry["ps_command"] = cmd
    entry["argv_has_user_data_dir"] = "--user-data-dir" in cmd
    entry["argv_has_enable_automation"] = "--enable-automation" in cmd
    entry["argv_flags"] = [tok for tok in cmd.split() if tok.startswith("--")]
    entry["total_ms"] = round(lsof_ms + entry["ps_ms"], 1)
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enable-automation", action="store_true")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--port", type=int, default=0, help="0 = pick free 30000-39999")
    args = ap.parse_args()

    port = args.port
    if not port:
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        port = 30000 + (port % 10000)

    profile = tempfile.mkdtemp(prefix="s0-attest-", dir="/tmp")
    os.chmod(profile, 0o700)
    argv = [
        CHROME,
        f"--user-data-dir={profile}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        # throwaway profile: keep the no-Keychain contract used by
        # scripts/qualification/smc_browser_live_navigation.py for ephemeral dirs
        "--use-mock-keychain",
        "--password-store=basic",
    ]
    if args.enable_automation:
        argv.append("--enable-automation")
    if args.headless:
        argv.append("--headless=new")
    argv.append("about:blank")

    chrome_log = tempfile.NamedTemporaryFile(prefix="s0-chrome-", suffix=".log", delete=False)
    proc = subprocess.Popen(argv, stdout=chrome_log, stderr=subprocess.STDOUT, start_new_session=True)
    facts: dict = {
        "variant": {
            "enable_automation": args.enable_automation,
            "headless": args.headless,
            "port": port,
            "profile": profile,
            "chrome_pid": proc.pid,
        }
    }
    try:
        try:
            wait_for_endpoint(f"http://127.0.0.1:{port}/json/version")
        except TimeoutError:
            facts["harness_error"] = "debug endpoint timeout"
            print(json.dumps(facts, ensure_ascii=False))
            return 2

        version = http_get_json(f"http://127.0.0.1:{port}/json/version")
        browser_ws = version.get("webSocketDebuggerUrl", "")
        facts["json_version"] = {
            "Browser": version.get("Browser"),
            "webSocketDebuggerUrl": browser_ws,
            "browser_ws_uuid_path": browser_ws.split("@")[-1] if browser_ws else None,
        }

        # 1) browser-level getBrowserCommandLine (the gated method under test)
        facts["getBrowserCommandLine"] = cdp_call(browser_ws, "Browser.getBrowserCommandLine")

        # 2) page-target side-effect probe: navigator.webdriver
        targets = http_get_json(f"http://127.0.0.1:{port}/json/list")
        page_ws = next(
            (t.get("webSocketDebuggerUrl") for t in targets if isinstance(t, dict) and t.get("type") == "page"),
            None,
        )
        if page_ws:
            facts["navigator_webdriver"] = cdp_call(
                page_ws, "Runtime.evaluate",
                {"expression": "navigator.webdriver", "returnByValue": True},
            )
        else:
            facts["navigator_webdriver"] = {"ok": False, "error": "no page target"}

        # 3) host-side attestation path (lsof -> PID -> ps argv)
        facts["host_side_attestation"] = host_side_attestation(port)
        print(json.dumps(facts, ensure_ascii=False))
        return 0
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
        shutil.rmtree(profile, ignore_errors=True)
        chrome_log.close()
        os.unlink(chrome_log.name)


if __name__ == "__main__":
    sys.exit(main())
