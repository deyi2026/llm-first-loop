"""探针 no_proxy/NO_PROXY 双变量写入逻辑测试（①）.

背景（实测）：websockets 15 经 urllib.request.getproxies() 取代理；macOS 系统
代理会把 wss:// 改写成 socks5h:// 导致企微端点隧道不通。urllib 的
getproxies_environment() 只有在 no_proxy 非空时才返回非空 dict——所以
no_proxy 与 NO_PROXY 两个环境变量都必须写，单写大写不生效。
"""

import importlib.util
import os
from pathlib import Path

from llm_loop.wecom.config import ensure_proxy_bypass

_PROBE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "wecom" / "wecom_sdk_probe.py"
)


def _load_probe():
    spec = importlib.util.spec_from_file_location("wecom_sdk_probe", _PROBE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_probe_writes_both_no_proxy_vars(monkeypatch):
    """探针 _ensure_proxy_bypass 必须同时写 no_proxy 与 NO_PROXY（env 分支触发条件）."""
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    probe = _load_probe()
    probe._ensure_proxy_bypass(["openws.work.weixin.qq.com"])
    assert "openws.work.weixin.qq.com" in os.environ["no_proxy"]
    assert "openws.work.weixin.qq.com" in os.environ["NO_PROXY"]


def test_probe_bypass_idempotent_and_preserves_existing(monkeypatch):
    """幂等：重复调用不产生重复项；已有绕过项保留（与 config.ensure_proxy_bypass 一致）."""
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    probe = _load_probe()
    probe._ensure_proxy_bypass(["openws.work.weixin.qq.com"])
    probe._ensure_proxy_bypass(["openws.work.weixin.qq.com"])
    assert os.environ["no_proxy"] == "localhost,127.0.0.1,openws.work.weixin.qq.com"
    assert os.environ["NO_PROXY"] == os.environ["no_proxy"]


def test_config_ensure_proxy_bypass_idempotent(monkeypatch):
    """仓库实现 ensure_proxy_bypass 幂等性（探针与之语义对齐）."""
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    first = ensure_proxy_bypass(["a.example.com"])
    second = ensure_proxy_bypass(["a.example.com"])
    assert first == second == "a.example.com"
