"""B2(2026-08-14) examples/api 文档防回归测试（零 LLM 零网络）.

覆盖: api.md 存在且含关键接口符号 / 三个示例 py_compile / 03 自定义工具可执行
（无需 key 的注册+执行链路）/ 01/02 引用符号在源码中存在（防文档漂移）。
"""

from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _ROOT / "examples"
_API_DOC = _ROOT / "docs" / "api.md"


def test_api_doc_exists_and_covers_core_symbols():
    """api.md 存在且覆盖核心公共接口（防文档漂移）."""
    text = _API_DOC.read_text(encoding="utf-8")
    for symbol in [
        "load_settings",
        "load_env_file",
        "build_engine",
        "LoopEngine",
        "run_stream",
        "SessionStore",
        "ToolRegistry",
        "ToolResultStatus",
        "build_app",
        "set_approval_callback",
    ]:
        assert symbol in text, f"api.md 缺核心接口: {symbol}"


def test_examples_compile():
    """三个示例语法与导入正确."""
    for name in ("01_minimal_cli_loop.py", "02_web_embed.py", "03_custom_tool.py"):
        py_compile.compile(str(_EXAMPLES / name), doraise=True)


def test_example03_custom_tool_runs():
    """03 自定义工具可执行（注册→执行→schema，零网络）."""
    proc = subprocess.run(
        [sys.executable, str(_EXAMPLES / "03_custom_tool.py")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "你好，世界" in proc.stdout
    assert "greet" in proc.stdout


def test_examples_referenced_in_readme():
    """README 引用 examples 与 api.md（发现入口不丢）."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "examples/" in readme
    assert "docs/api.md" in readme


def test_run_single_convenience_entry(tmp_path, monkeypatch):
    """B5: run_single 自动建会话执行（一次性便捷入口）."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    class _Fake:
        def chat(self, messages, tools, **kw):
            return LLMResponse(content="一次性回答", tool_calls=[], provider="fake")

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return LLMResponse(content="一次性回答", tool_calls=[], provider="fake")

            return _gen()

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=ToolRegistry(),  # type: ignore[arg-type]
        memory=None,  # type: ignore[arg-type]
        session=SessionStore(tmp_path / "sessions"),
        settings=settings,
    )
    result = engine.run_single("你好")
    assert result.final_answer == "一次性回答"
    assert result.session_id  # 自动创建了会话
    assert engine.session.exists(result.session_id)  # 会话已落盘可追溯
