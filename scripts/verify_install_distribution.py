"""Verify a built wheel outside the checkout, without model/provider access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

GUARD = """
import ipaddress, os, socket
_original = socket.socket.connect
_original_ex = socket.socket.connect_ex
_original_dns = socket.getaddrinfo
def _check(address):
    if not isinstance(address, tuple):
        return
    try:
        local = ipaddress.ip_address(address[0]).is_loopback
    except ValueError:
        local = address[0] == 'localhost'
    if not local or address[1] != int(os.environ['LFL_SMOKE_PORT']):
        with open(os.environ['LFL_SMOKE_NETWORK_LOG'], 'a') as log:
            log.write('unexpected connection\\n')
        raise OSError('Installation smoke forbids provider/external connections')
def _connect(self, address):
    _check(address)
    return _original(self, address)
def _connect_ex(self, address):
    _check(address)
    return _original_ex(self, address)
def _dns(host, port, *args, **kwargs):
    if host not in (None, 'localhost', '127.0.0.1', '::1'):
        _check((host, port))
    return _original_dns(host, port, *args, **kwargs)
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _dns
"""


def run(args, *, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args[0]}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def fetch(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
        assert response.status == 200
        return response.read()


def verify_server(command, root, env, port, workspace):
    log = root / "server.log"
    with log.open("w") as stream:
        process = subprocess.Popen(command, cwd=root / "workspace", env=env, stdout=stream, stderr=stream)
        try:
            deadline = time.monotonic() + 45
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Installed Web exited:\n" + log.read_text())
                try:
                    fetch(port, "/health")
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Installed Web startup timed out:\n" + log.read_text()) from None
                    time.sleep(0.2)
            html = fetch(port, "/ui/v2/").decode("utf-8")
            assets = re.findall(r'(?:src|href)="(/ui/v2/assets/[^"]+)"', html)
            assert assets, "Installed UI contains no compiled assets"
            for asset in assets:
                assert fetch(port, asset), asset
            registry = json.loads(fetch(port, "/api/v1/workspaces"))
            current = next(item for item in registry["workspaces"] if item["id"] == registry["current"])
            assert Path(current["path"]) == workspace, "Web selected the runtime directory instead of the requested workspace"
            return {"health": 200, "ui": 200, "assets_checked": len(assets), "workspace_bound": True}
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def verify(wheel, *, offline):
    with tempfile.TemporaryDirectory(prefix="lfl-wheel-smoke-") as temporary:
        root = Path(temporary).resolve()
        workspace = root / "workspace"
        workspace.mkdir()
        env = {k: v for k, v in os.environ.items() if k in {
            "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "LANG",
            "LC_ALL", "UV_CACHE_DIR", "SSL_CERT_FILE", "SSL_CERT_DIR",
        }}
        venv = root / "venv"
        run(["uv", "venv", "--python", sys.executable, str(venv)], cwd=root, env=env)
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install = ["uv", "pip", "install", "--python", str(python), str(wheel)]
        run(install + (["--offline"] if offline else []), cwd=root, env=env)
        run(["uv", "pip", "check", "--python", str(python)], cwd=root, env=env)
        lfl = str(venv / ("Scripts/lfl.exe" if os.name == "nt" else "bin/lfl"))
        env.update({
            "LFL_HOME": str(root / "state"), "PYTHONNOUSERSITE": "1",
            "LEARNING_PLANE_ENABLED": "0", "METHOD_REFLECTION_MODE": "off",
            "LLM_API_KEY": "installation-smoke-not-a-real-key",
            "LLM_BASE_URL": "http://127.0.0.1:1/v1", "LLM_MODEL": "installation-smoke",
            "RUNTIME_IDENTITY_MODE": "enforce",
        })
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        guard = root / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(GUARD)
        env.update({
            "WEB_HOST": "127.0.0.1", "WEB_PORT": str(port), "LFL_SMOKE_PORT": str(port),
            "LFL_SMOKE_NETWORK_LOG": str(root / "unexpected-network.log"), "PYTHONPATH": str(guard),
        })
        version = run([lfl, "--version"], cwd=workspace, env=env).strip()
        integrity = json.loads(run([lfl, "check-install"], cwd=workspace, env=env))
        assert integrity["ok"], integrity
        paths = json.loads(run([lfl, "paths"], cwd=workspace, env=env))
        assert Path(paths["DATA_DIR"]) == root / "state/data"
        assert Path(paths["SKILLS_DIR"]).is_relative_to(venv)
        run([lfl, "chat", "--help"], cwd=workspace, env=env)
        run([lfl, "event-inventory"], cwd=workspace, env=env)
        selected = root / "selected-workspace"
        selected.mkdir()
        server = verify_server([lfl, "--workspace", str(selected), "web"], root, env, port, selected)
        assert not (root / "unexpected-network.log").exists(), "Smoke attempted provider/external access"
        assert not (workspace / "data").exists(), "State leaked into arbitrary CWD"
        assert not list(venv.glob("lib/python*/data")), "State leaked into the Python installation"
        return {
            "ok": True, "version": version,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "resource_integrity": integrity, "web": server, "provider_calls": 0,
            "fresh_venv": True, "source_checkout_on_pythonpath": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = verify(args.wheel.resolve(strict=True), offline=args.offline)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
