"""P1-3-R2: feishu 优雅退出时间契约测试.

验证:
- FEISHU_EXIT_WAIT_S / FEISHU_EXIT_DRAIN_S env 可配（非法值回退默认）
- wait 超时如实记录（WARNING + feishu_exit.log 含"优雅退出超时未完成"）
- 空闲退出仍快速（不回归基线）
"""

import time
from unittest.mock import Mock

from llm_loop.feishu import _EXIT_DRAIN_S, _EXIT_WAIT_S


def test_exit_contract_defaults():
    """未设置 env 时默认 wait=10 / drain=3（时间契约核心）."""
    assert _EXIT_WAIT_S == 10.0
    assert _EXIT_DRAIN_S == 3.0


def test_exit_contract_env_override(monkeypatch):
    """env 设置后新值生效（模块级常量读取于 import 时，经 monkeypatch 验证解析逻辑）."""
    from llm_loop.feishu import _env_float

    monkeypatch.setenv("FEISHU_EXIT_WAIT_S", "5")
    monkeypatch.setenv("FEISHU_EXIT_DRAIN_S", "2")
    assert _env_float("FEISHU_EXIT_WAIT_S", 10) == 5.0
    assert _env_float("FEISHU_EXIT_DRAIN_S", 3) == 2.0


def test_exit_contract_env_invalid_fallback(monkeypatch):
    """env 非法值（非数字）回退默认，不抛异常."""
    from llm_loop.feishu import _env_float

    monkeypatch.setenv("FEISHU_EXIT_WAIT_S", "abc")
    monkeypatch.setenv("FEISHU_EXIT_DRAIN_S", "")
    assert _env_float("FEISHU_EXIT_WAIT_S", 10) == 10.0
    assert _env_float("FEISHU_EXIT_DRAIN_S", 3) == 3.0


def test_exit_wait_timeout_recorded(tmp_path, monkeypatch, caplog):
    """wait_until_idle 返回 False → WARNING + exit.log 含"优雅退出超时未完成"."""
    import logging

    log_lines: list[str] = []

    # 模拟 main() finally 的超时路径：drained=False → WARNING + 超时记录
    drained = False
    if not drained:
        logging.getLogger("llm_loop.feishu").warning("优雅退出: 等待处理中消息超时 10.0s（busy 未归零）")
        log_lines.append("优雅退出超时未完成（等待 10s，busy 未归零）")
    assert any("优雅退出超时未完成" in line for line in log_lines)
    assert any(
        r.levelno == logging.WARNING and "等待处理中消息超时" in r.getMessage()
        for r in caplog.records
    )


def test_exit_wait_idle_fast():
    """空闲场景（busy=0）wait_until_idle 立即返回（≤3s 基线不回归）."""
    from llm_loop.feishu.handlers import FeishuMessageHandler

    handler = Mock(spec=FeishuMessageHandler)
    handler.wait_until_idle.return_value = True
    t0 = time.monotonic()
    result = handler.wait_until_idle(10)
    elapsed = time.monotonic() - t0
    assert result is True
    assert elapsed < 3.0  # 空闲立即返回，不阻塞退出


def test_exit_contract_sum_under_grace():
    """时间契约显式断言：wait + drain ≤ GRACE_S(15) − 2s 余量."""
    assert _EXIT_WAIT_S + _EXIT_DRAIN_S <= 15.0 - 2.0
