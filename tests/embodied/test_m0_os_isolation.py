"""M0-G3/G4 kernel-enforced isolation test (synthetic file, safe device, loopback)."""

from __future__ import annotations

import subprocess
import sys

import pytest
from m0_isolation_probe import run

from tests import env_channel

# Capture trusted process launcher before the M0-A autouse sentinel patches it.
# This test alone launches a bounded sandboxed child; all other tests keep the sentinel.
_ORIGINAL_RUN = subprocess.run
_ORIGINAL_POPEN = subprocess.Popen


def test_kernel_isolation_denies_oracle_network_and_device(monkeypatch):
    if sys.platform != "darwin":
        pytest.skip("macOS kernel sandbox receipt required on Mac Host")
    if env_channel.nested_sandbox_exec():
        pytest.skip("nested sandbox-exec: inner sandbox_apply is EPERM")
    with monkeypatch.context() as scoped:
        scoped.setattr(subprocess, "run", _ORIGINAL_RUN)
        scoped.setattr(subprocess, "Popen", _ORIGINAL_POPEN)
        receipt = run()
    assert receipt["os_enforced"] is True
    assert receipt["separate_process"] is True
    assert receipt["oracle_read_denied"] is True
    assert receipt["device_read_denied"] is True
    assert receipt["network_connect_denied"] is True
    assert receipt["network_bind_denied"] is True
    assert receipt["oracle_env_absent"] is True
    assert receipt["oracle_canary_leaked"] is False
    # Deliberate honesty: the kernel sandbox isolates access, not the UNIX UID.
    assert receipt["separate_uid"] is False
