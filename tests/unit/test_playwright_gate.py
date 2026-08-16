"""playwright 执行门控测试（EVO-20260816-96215428 阶段一）.

覆盖：①执行层 URL 沙箱再校验（纵深防御，confirm=true 路径仍被拦截）；
②参数层拦截既有行为不回归。真实浏览器执行不在单测覆盖（需 chromium）。
"""

from llm_loop.introspection.tools_playwright import run_playwright_test


def test_exec_layer_blocks_sandbox_violation(tmp_path, monkeypatch):
    """confirm=true 的执行路径仍过执行层 URL 校验（白名单外 URL 被拒绝）."""
    monkeypatch.chdir(tmp_path)  # 审计落盘隔离到 tmp
    r = run_playwright_test(None, None, {
        "scenario": "访问外部站点",
        "url": "https://evil.example.com/steal",
        "confirm": True,
    })
    assert r.status.value == "failure"
    assert "URL 沙箱拒绝" in r.content


def test_param_layer_blocks_before_dry_run(tmp_path, monkeypatch):
    """参数层拦截不回归：dry_run（confirm=false）也先过白名单."""
    monkeypatch.chdir(tmp_path)
    r = run_playwright_test(None, None, {
        "scenario": "访问外部站点",
        "url": "http://192.168.1.1:8080/admin",
        "confirm": False,
    })
    assert r.status.value == "failure"
    assert "URL 沙箱拒绝" in r.content


def test_allowed_url_passes_gate_to_dry_run(tmp_path, monkeypatch):
    """白名单内 URL（localhost）dry_run 正常生成脚本（门控不误伤合法用例）."""
    monkeypatch.chdir(tmp_path)
    r = run_playwright_test(None, None, {
        "scenario": "访问首页。截图。",
        "url": "http://localhost:8080/",
        "confirm": False,
    })
    assert r.status.value == "success"
    assert "脚本已生成" in r.content
