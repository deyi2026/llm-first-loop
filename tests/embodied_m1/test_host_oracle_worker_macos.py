"""No-root tests for the frozen, independently executable macOS Host Oracle."""
from __future__ import annotations

import importlib.util
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest

from tests import env_channel

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "scripts/embodied/m1_host_oracle_worker_macos.py"
PROFILE = ROOT / "scripts/embodied/m1_host_oracle_macos.sb"
INSTALLER = ROOT / "scripts/embodied/install_oracle_host_macos.sh"


@pytest.fixture(scope="module")
def host_worker():
    spec = importlib.util.spec_from_file_location("m1_host_oracle_worker_macos", WORKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(*, weld=True, contact=True, z=0.06, kind="grasp"):
    return {
        "snapshot": {
            "cube": {"pos": [0.1, 0.0, z], "vel": [0.0, 0.0, 0.0]},
            "contact_pairs": ([["cube_geom", "fingertip_left", -0.001]]
                              if contact else []),
            "weld_active": weld,
        },
        "claim_kind": kind, "scene_epoch": 3, "experiment_id": "M1-UID463-UNIT",
    }


def test_host_oracle_judgement_positive_and_fail_closed(host_worker):
    assert host_worker.judge_payload(_case())["verdict"] == "success"
    assert host_worker.judge_payload(_case(weld=False))["verdict"] == "failure"
    assert host_worker.judge_payload(_case(contact=False))["verdict"] == "failure"
    assert host_worker.judge_payload(_case(z=0.03))["verdict"] == "failure"
    place = _case(kind="place", weld=False, z=0.04)
    place["tray_pos"] = [0.1, 0.0, 0.01]
    place["snapshot"]["contact_pairs"] = [["cube_geom", "tray_floor", -0.001]]
    assert host_worker.judge_payload(place)["verdict"] == "success"
    place["snapshot"]["weld_active"] = True
    assert host_worker.judge_payload(place)["verdict"] == "failure"
    place["snapshot"]["weld_active"] = False
    place["snapshot"]["contact_pairs"] = []
    assert host_worker.judge_payload(place)["verdict"] == "failure"
    place["snapshot"]["contact_pairs"] = [["cube_geom", "tray_floor", -0.001]]
    place["snapshot"]["cube"]["pos"][2] = 0.077
    assert host_worker.judge_payload(place)["verdict"] == "failure"
    place["snapshot"]["cube"]["pos"][2] = 0.04
    place["tray_pos"] = [0.0, 0.18, 0.01]
    assert host_worker.judge_payload(place)["verdict"] == "failure"


@pytest.mark.parametrize("change", [
    {"claim_kind": "shell"},
    {"scene_epoch": "3"},
    {"experiment_id": ""},
    {"snapshot": {}},
    {"snapshot": {"cube": {"pos": [0.1, 0.0, float("nan")],
                            "vel": [0.0, 0.0, 0.0]},
                  "contact_pairs": [], "weld_active": True}},
])
def test_host_oracle_rejects_malformed(host_worker, change):
    payload = _case()
    payload.update(change)
    with pytest.raises(ValueError):
        host_worker.judge_payload(payload)


def test_fixed_worker_rejects_wrong_uid_without_sudo():
    proc = subprocess.run(
        ["/usr/bin/python3", "-I", "-S", "-B", str(WORKER)],
        input=json.dumps(_case()), text=True, capture_output=True, timeout=10, check=False,
    )
    assert proc.returncode == 77
    assert json.loads(proc.stdout)["verdict"] == "failure"


def test_fixed_installation_contract():
    worker = WORKER.read_bytes()
    profile = PROFILE.read_text()
    installer = INSTALLER.read_text()
    assert b"import llm_loop" not in worker
    assert "(deny network*)" in profile
    assert "(deny file-write*)" in profile
    assert '(deny file-read* (subpath "/Users"))' in profile
    assert "NOPASSWD:NOSETENV:" in installer
    assert "sudoers_file=/private/etc/sudoers.d/lfl-oracle-v1" in installer
    assert "/usr/bin/cat" not in installer  # macOS cat lives in /bin
    assert "/bin/cat" in installer
    assert b"oracle_uid" in worker
    assert "root_dir=/Library/PrivilegedHelperTools/lfl-oracle-v1" in installer


@pytest.mark.skipif(
    sys.platform != "darwin" or env_channel.nested_sandbox_exec(),
    reason="macOS Seatbelt only (nested sandbox-exec cannot apply profiles)",
)
def test_kernel_profile_denies_network_device_and_write(tmp_path):
    script = """
import errno,json,socket,sys
def denied(f):
 try: f()
 except OSError as e: return e.errno in (errno.EPERM, errno.EACCES)
 return False
out = {
 'network': denied(lambda: socket.socket().connect(('127.0.0.1', 9))),
 'device': denied(lambda: open('/dev/null').read()),
 'write': denied(lambda: open(sys.argv[1], 'w').write('x')),
 'user_read': denied(lambda: open(sys.argv[2]).read()),
}
print(json.dumps(out,sort_keys=True))
"""
    # The path need not exist: Seatbelt denies before filesystem lookup.
    proc = subprocess.run(
        ["/usr/bin/sandbox-exec", "-f", str(PROFILE),
         "/usr/bin/python3", "-I", "-S", "-B", "-c", script,
         str(tmp_path / "forbidden"), str(Path(pwd.getpwuid(os.getuid()).pw_dir) / ".profile")],
        text=True, capture_output=True, timeout=12, check=False,
    )
    assert proc.returncode == 0, proc.stderr[:200]
    assert all(json.loads(proc.stdout).values())
