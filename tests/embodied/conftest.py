"""tests/embodied 公共夹具（M0-A，DESIGN v2.3 §11.1.1）。

- sys.path 注入：让测试模块可直接 import 同目录 stubs（--import-mode=importlib 下必需）。
- SideEffectSentinel：测试进程内 fail-closed 哨兵（合同第 6 项的独立拦截面）。
  任何 socket / subprocess / os.system / os.popen 调用都会被记录并抛 AssertionError，
  与双桩自身 nw/hw 计数器构成双口径零副作用证据。
- 本 conftest 仅作用于 tests/embodied/ 目录，不影响仓库其他测试。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


class SideEffectSentinel:
    """真实设备 / 外部网络副作用哨兵：只观测本目录测试进程内的危险入口。"""

    def __init__(self) -> None:
        self.blocked: list[str] = []

    def _deny(self, name: str):
        def _blocked(*args, **kwargs):
            self.blocked.append(name)
            raise AssertionError(f"forbidden hardware/network side effect attempted: {name}")

        return _blocked

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(socket, "socket", self._deny("socket.socket"))
        monkeypatch.setattr(socket, "create_connection", self._deny("socket.create_connection"))
        monkeypatch.setattr(subprocess, "Popen", self._deny("subprocess.Popen"))
        monkeypatch.setattr(subprocess, "run", self._deny("subprocess.run"))
        monkeypatch.setattr(os, "system", self._deny("os.system"))
        monkeypatch.setattr(os, "popen", self._deny("os.popen"))


@pytest.fixture(autouse=True)
def side_effect_sentinel(monkeypatch: pytest.MonkeyPatch) -> SideEffectSentinel:
    sentinel = SideEffectSentinel()
    sentinel.install(monkeypatch)
    return sentinel
