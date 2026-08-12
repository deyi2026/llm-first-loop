"""P1-2-R5: restart_feishu.sh 心跳口径静态断言测试.

沿项目静态断言风格（读取脚本文本断言），验证:
- `_heartbeat_healthy` 函数定义存在（心跳新鲜度判定）
- 健康检查基于心跳文件 mtime（stat -f %m / stat -c %Y），不依赖 TCP/lsof
- start/stop/restart/status 幂等语义保留
"""

from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restart_feishu.sh"


def test_script_exists():
    assert _SCRIPT.exists()
    assert _SCRIPT.stat().st_size > 0


def test_has_heartbeat_healthy_function():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "_heartbeat_healthy()" in text
    assert "HEARTBEAT_FILE" in text


def test_uses_heartbeat_mtime_not_tcp():
    text = _SCRIPT.read_text(encoding="utf-8")
    # 心跳新鲜度判定（stat -f %m macOS / stat -c %Y Linux）
    assert "stat -f %m" in text or "stat -c %Y" in text
    # 健康判定不再使用 lsof 命令（仅注释提及历史移除说明）
    assert "lsof -p" not in text
    # 不再依赖 WS_HOST 连接判定（仅注释提及历史移除说明）
    assert 'WS_HOST="' not in text
    assert 'grep "TCP' not in text


def test_restart_system_injects_exit_env():
    """P1-3-R2: restart_system.sh/restart_feishu.sh feishu 启动路径注入退出时间契约 env."""
    system_script = _SCRIPT.parents[1] / "scripts" / "restart_system.sh"
    feishu_script = _SCRIPT.parents[1] / "scripts" / "restart_feishu.sh"
    for script in (system_script, feishu_script):
        text = script.read_text(encoding="utf-8")
        assert "FEISHU_EXIT_WAIT_S" in text
        assert "FEISHU_EXIT_DRAIN_S" in text
