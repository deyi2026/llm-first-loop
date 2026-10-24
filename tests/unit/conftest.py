"""tests/unit 的局部夹具。

P1-2 之后浏览器默认拒绝环回/私网目标；而本目录的浏览器用例把 http://127.0.0.1
当作"页面夹具"（不是安全断言）。这里只在用例文件名含 browser 时显式授权，
避免把"夹具限制"误读成"策略回归"；生产默认拒绝仍由
tests/test_browser_site_policy.py 独立守护，不受本夹具影响。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _allow_loopback_browser_fixture(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if "browser" not in request.node.path.name:
        return
    monkeypatch.setenv("LFL_BROWSER_ALLOWED_HOSTS", "127.0.0.1,localhost")
