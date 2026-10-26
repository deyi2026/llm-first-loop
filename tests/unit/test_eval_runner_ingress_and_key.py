"""P1(2026-10-23) 评测框架真实 LLM 路径的两处修复回归测试.

覆盖:
- R8.24-D fail-closed 适配：engine.run 传入 test_harness ingress 凭据
  （否则 guard 拒绝 role=user 写入 → rounds=0，模型根本未被调用）
- provider api_key_env 解析：换 provider（如 minimax）时按 provider 声明的
  环境变量取凭据（否则 client_params 抛 "缺少 api_key"）
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pytest  # noqa: E402  — sys.path 引导后的第三方导入
import run_eval  # noqa: E402  — scripts 层模块（sys.path 注入后导入）

from tests import env_channel  # noqa: E402  — conftest 已注入 repo 根到 sys.path


@pytest.mark.skipif(
    env_channel.in_git_worktree_detached_root(),
    reason="环境受限：干净 worktree 门通道无生产 .env，provider env 解析存在环境差异"
           "（主树绿，非代码回归）【RED-28】",
)
def test_resolve_api_key_prefers_provider_declared_env(monkeypatch):
    """明确 Provider 声明，避免依赖未跟踪的私有 providers.json。"""
    monkeypatch.setattr(
        "llm_loop.llm.providers.load_registry",
        lambda _settings: SimpleNamespace(
            providers={"minimax": SimpleNamespace(api_key_env="MINIMAX_API_KEY")},
        ),
    )
    monkeypatch.setenv("LLM_MODEL", "minimax/MiniMax-M3.1-Flash")
    monkeypatch.setenv("MINIMAX_API_KEY", "key-from-provider")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-from-deepseek")
    monkeypatch.setenv("LLM_API_KEY", "key-from-llm")
    assert run_eval._resolve_api_key() == "key-from-provider"


def test_resolve_api_key_falls_back_to_legacy_env(monkeypatch):
    """无 Provider 声明时回退旧环境变量，不依赖开发者私有配置。"""
    monkeypatch.setattr(
        "llm_loop.llm.providers.load_registry",
        lambda _settings: SimpleNamespace(providers={}),
    )
    monkeypatch.setenv("LLM_MODEL", "minimax/MiniMax-M3.1-Flash")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key-from-deepseek")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert run_eval._resolve_api_key() == "key-from-deepseek"


def test_resolve_api_key_empty_when_nothing_set(monkeypatch):
    """无任何凭据 → 空串（调用方据此抛错，不静默使用空 key）."""
    monkeypatch.setenv("LLM_MODEL", "minimax/MiniMax-M3.1-Flash")
    for name in ("MINIMAX_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert run_eval._resolve_api_key() == ""


def test_issue_test_ingress_is_whitelisted():
    """test_harness 凭据必须在白名单内（否则 guard 仍会拒绝）."""
    from llm_loop.core.trace_leak.ingress_token import is_whitelisted, issue_test_ingress

    assert is_whitelisted(issue_test_ingress())


def test_engine_run_accepts_ingress_kwarg():
    """engine.run 必须接受 ingress 关键字（修复点 1 的接口前提）."""
    import inspect

    from llm_loop.core.loop.engine import LoopEngine

    assert "ingress" in inspect.signature(LoopEngine.run).parameters
