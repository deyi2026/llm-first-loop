"""playwright_exec 单 exec 工具测试（EVO-20260816-bfb9f215 阶段二）.

覆盖：AST 静态门控（禁 import playwright）、dry_run 回显、参数校验、
run_mode 注册可见性。真实浏览器执行不在单测覆盖（需 chromium + 网关在线）。
"""

from llm_loop.introspection.tools_playwright_exec import (
    PLAYWRIGHT_EXEC_TOOL_DEF,
    _scan_code,
    run_playwright_exec,
)

# ── AST 静态门控 ──


def test_scan_blocks_import_playwright():
    ok, err = _scan_code("import playwright\nprint('x')")
    assert not ok and "禁止 import playwright" in err


def test_scan_blocks_from_playwright():
    ok, err = _scan_code("from playwright.sync_api import sync_playwright")
    assert not ok and "禁止" in err


def test_scan_allows_helper_usage():
    ok, _ = _scan_code('# 打开首页\ngoto("http://localhost:8080/")\nprint(axtree_text())')
    assert ok


def test_scan_reports_syntax_error():
    ok, err = _scan_code("def broken(:\n")
    assert not ok and "语法错误" in err


# ── 工具行为 ──


def test_empty_code_fails():
    r = run_playwright_exec(None, None, {"code": "  "})
    assert r.status.value == "failure" and "参数错误" in r.content


def test_dry_run_returns_preview(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = run_playwright_exec(None, None, {
        "code": '# 步骤\ngoto("http://localhost:8080/")',
        "confirm": False,
    })
    assert r.status.value == "success"
    assert "dry_run" in r.content and "静态检查通过" in r.content


def test_blocked_code_rejected_even_with_confirm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = run_playwright_exec(None, None, {
        "code": "import playwright\nprint(1)",
        "confirm": True,
    })
    assert r.status.value == "failure" and "静态门控拒绝" in r.content


def test_tool_def_description_contract():
    """描述含钉死 helper 摘要 + 状态契约 + 何时不用（AX L1 规范）."""
    d = PLAYWRIGHT_EXEC_TOOL_DEF["description"]
    assert len(d) <= 2048, f"描述超 2KB: {len(d)}"
    for kw in ("goto(url)", "axtree_text()", "状态契约", "何时不用", "confirm=true"):
        assert kw in d, f"描述缺要素: {kw}"


# ── run_mode 注册可见性（阶段一门控覆盖新工具）──


def _settings(tmp_path, run_mode: str):
    from llm_loop.config import Settings

    return Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        run_mode=run_mode,
        extract_enabled=False,
        docs_dir="",
    )


def _registered_names(engine) -> set[str]:
    return set(engine.registry._tools.keys())  # noqa: SLF001


def test_exec_hidden_in_minimal_and_ptc(tmp_path):
    from llm_loop.factory import build_engine

    for mode in ("minimal", "ptc"):
        names = _registered_names(build_engine(_settings(tmp_path / mode, mode)))
        assert "playwright_exec" not in names, f"playwright_exec 应在 {mode} 隐藏"


def test_exec_visible_in_standard_and_creative(tmp_path):
    from llm_loop.factory import build_engine

    for mode in ("standard", "creative"):
        names = _registered_names(build_engine(_settings(tmp_path / mode, mode)))
        assert "playwright_exec" in names, f"playwright_exec 应在 {mode} 可见"
