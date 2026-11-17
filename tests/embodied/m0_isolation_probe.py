"""M0-G3/G4 OS isolation probe. Run directly, outside the M0-A in-memory pytest sentinel.

No robot device, external network, simulator or provider is contacted. The child
only attempts a denied read of a synthetic Oracle file, /dev/null and a denied
loopback connect/bind. Fail closed if sandbox-exec cannot enforce the boundary.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_CHILD = r"""
import errno
import json
import os
import socket
import sys

def denied(fn):
    try:
        fn()
    except OSError as exc:
        return exc.errno == errno.EPERM
    return False

def network_connect():
    with socket.socket() as sock:
        sock.settimeout(0.2)
        sock.connect(('127.0.0.1', 9))

def network_bind():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))

result = {
    'child_pid': os.getpid(),
    'child_uid': os.getuid(),
    'oracle_read_denied': denied(lambda: open(sys.argv[1], encoding='utf-8').read()),
    'device_read_denied': denied(lambda: open('/dev/null', encoding='utf-8').read()),
    'network_connect_denied': denied(network_connect),
    'network_bind_denied': denied(network_bind),
    'oracle_env_absent': not any('ORACLE_' in key for key in os.environ),
}
print(json.dumps(result, sort_keys=True))
"""


def run() -> dict[str, object]:
    sandbox = shutil.which("sandbox-exec")
    if sys.platform != "darwin" or not sandbox:
        raise RuntimeError("M0-G3/G4 NO-GO: macOS sandbox-exec unavailable")
    with tempfile.TemporaryDirectory(prefix="lfl-m0-oracle-") as tmp:
        oracle_dir = Path(tmp, "oracle").resolve()
        oracle_dir.mkdir(mode=0o700)
        oracle_file = oracle_dir / "privileged_state.json"
        canary = "ORACLE_CANARY_" + secrets.token_hex(16)
        oracle_file.write_text(json.dumps({"canary": canary, "exact_pose": 0.123456789}))
        oracle_file.chmod(0o600)

        # A kernel-enforced per-process sandbox, not a mere Python monkeypatch.
        # Explicitly deny the synthetic Oracle path, safe device and network.
        profile = (
            '(version 1)(allow default)(deny network*)'
            f'(deny file-read* (subpath {json.dumps(str(oracle_dir))}))'
            '(deny file-read* (literal "/dev/null"))'
        )
        child = subprocess.run(
            [sandbox, "-p", profile, sys.executable, "-c", _CHILD, str(oracle_file)],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if child.returncode != 0:
            raise RuntimeError(f"M0-G3/G4 NO-GO: sandbox child exited {child.returncode}")
        result = json.loads(child.stdout.strip())
        required = (
            "oracle_read_denied",
            "device_read_denied",
            "network_connect_denied",
            "network_bind_denied",
            "oracle_env_absent",
        )
        if not all(result.get(key) is True for key in required):
            raise RuntimeError("M0-G3/G4 NO-GO: one or more OS isolation probes failed")
        if canary in child.stdout or canary in child.stderr:
            raise RuntimeError("M0-G4 NO-GO: Oracle canary leaked")
        if result["child_pid"] == os.getpid():
            raise RuntimeError("M0-G4 NO-GO: process isolation absent")
        return {
            "schema": "lfl.embodied.m0-isolation/v1",
            "os_enforced": True,
            "sandbox": "macos-sandbox-exec",
            "separate_process": True,
            "separate_uid": result["child_uid"] != os.getuid(),
            "oracle_read_denied": result["oracle_read_denied"],
            "device_read_denied": result["device_read_denied"],
            "network_connect_denied": result["network_connect_denied"],
            "network_bind_denied": result["network_bind_denied"],
            "oracle_env_absent": result["oracle_env_absent"],
            "oracle_canary_leaked": False,
            "note": "Kernel sandbox protects same-UID processes; distinct-UID isolation is NOT claimed",
        }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
