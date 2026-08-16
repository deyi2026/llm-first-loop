"""EVO-20260814 P1-A: RUN_MODE 运行模式（对齐 Harness 四种运行模式）.

standard: 全工具集（默认零回归）
ptc:      命令执行为主路径（web 检索降级禁用）
minimal:  精简工具集（只读+必要执行，外围工具禁用）
creative: 宽松默认参数（超时/输出上限放大）
"""

from __future__ import annotations

from unittest import mock

from llm_loop.config import Settings


def _settings(tmp_path, run_mode: str = "standard") -> Settings:
    return Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        run_mode=run_mode,
        extract_enabled=False,
        docs_dir="",  # 禁用 docs 检索，缩小工具面
    )


def _registered_names(engine) -> set[str]:
    return set(engine.registry._tools.keys())  # noqa: SLF001


def test_run_mode_default_standard(tmp_path):
    """默认 standard（未设 RUN_MODE）→ 全工具集（web_fetch/web_search 存在）."""
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path))
    names = _registered_names(engine)
    assert "web_fetch" in names and "web_search" in names
    assert "execute_command" in names and "read_file" in names
    # EVO-20260816-96215428：playwright 门控放行端——standard 必须可见（防误伤）
    assert "playwright_test" in names, "playwright_test 应在 standard 下保留"


def test_run_mode_minimal_hides_peripheral(tmp_path):
    """minimal → 外围工具禁用（web/飞书/playwright/record_skill），核心保留."""
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path, "minimal"))
    names = _registered_names(engine)
    for hidden in ("web_fetch", "web_search", "send_feishu_message", "playwright_test", "record_skill"):
        assert hidden not in names, f"{hidden} 应在 minimal 下隐藏"
    for keep in ("read_file", "edit_file", "execute_command", "architecture_status",
                 "search_records", "event_stream", "search_docs", "adjust_strategy"):
        assert keep in names, f"{keep} 应在 minimal 下保留"


def test_run_mode_ptc_hides_web(tmp_path):
    """ptc → web 检索类 + playwright 隐藏（命令执行主路径），其余保留."""
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path, "ptc"))
    names = _registered_names(engine)
    assert "web_fetch" not in names and "web_search" not in names
    # EVO-20260816-96215428 阶段一门控：浏览器执行类工具 ptc 不可见（仅 standard/creative）
    assert "playwright_test" not in names, "playwright_test 应在 ptc 下隐藏（注册层门控）"
    assert "execute_command" in names and "send_feishu_message" in names  # 飞书保留


def test_run_mode_creative_keeps_all(tmp_path):
    """creative → 全工具集（同 standard，不隐藏任何工具）."""
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path, "creative"))
    names = _registered_names(engine)
    assert "web_fetch" in names and "web_search" in names
    assert "send_feishu_message" in names
    # EVO-20260816-96215428：playwright 门控放行端——standard/creative 必须可见（防误伤）
    assert "playwright_test" in names, "playwright_test 应在 creative 下保留"


def test_run_mode_exposed_in_status(tmp_path):
    """architecture_config 暴露 run_mode（AI 可查可验证）."""
    from llm_loop.factory import build_engine

    engine = build_engine(_settings(tmp_path, "ptc"))
    snap = engine.status.snapshot(dimensions=["architecture_config"])
    cfg = snap.get("architecture_config", {})
    assert cfg.get("run_mode") == "ptc"


def test_env_run_mode_invalid_falls_back_standard():
    """RUN_MODE 非法值回退 standard（不阻断启动，安全不受影响）."""
    from llm_loop.config import _env_run_mode

    with mock.patch.dict("os.environ", {"RUN_MODE": "bogus"}, clear=False):
        assert _env_run_mode("RUN_MODE") == "standard"
    with mock.patch.dict("os.environ", {"RUN_MODE": "minimal"}, clear=False):
        assert _env_run_mode("RUN_MODE") == "minimal"
    with mock.patch.dict("os.environ", {}, clear=False):
        assert _env_run_mode("RUN_MODE") == "standard"


def test_run_mode_in_status_dict(tmp_path):
    """Settings.to_status_dict 含 run_mode."""
    s = _settings(tmp_path, "creative")
    assert s.to_status_dict().get("run_mode") == "creative"
