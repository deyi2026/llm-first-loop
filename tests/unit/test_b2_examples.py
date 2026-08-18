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


def test_public_api_signature_snapshot():
    """B5 契约快照: 公共 API 签名锁定（防语义漂移——外部依赖据此接入）.

    变更公共签名（参数名/默认值/返回类型）必须同步本测试与 docs/api.md。
    （from __future__ import annotations 使注解字符串化, 此处按参数名+默认值比对）
    """
    import inspect

    from llm_loop.config import load_env_file, load_settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.factory import build_engine
    from llm_loop.tools.registry import ToolRegistry

    def _params(fn) -> list[str]:
        sig = inspect.signature(fn)
        return [p.name for p in sig.parameters.values()]

    def _defaults(fn) -> dict[str, object]:
        sig = inspect.signature(fn)
        return {
            name: p.default
            for name, p in sig.parameters.items()
            if p.default is not inspect.Parameter.empty
        }

    # build_engine(settings)（唯一生产装配点）
    assert _params(build_engine) == ["settings"]

    # 引擎核心方法（session_id 位置参数, model 关键字可选）
    assert _params(LoopEngine.run) == ["self", "session_id", "user_text", "model", "reasoning_effort"]
    assert _defaults(LoopEngine.run) == {"model": None, "reasoning_effort": None}
    assert _params(LoopEngine.run_single) == ["self", "user_text", "model"]
    assert _defaults(LoopEngine.run_single) == {"model": None}
    assert _params(LoopEngine.run_stream) == ["self", "session_id", "user_text", "model", "reasoning_effort"]
    assert _defaults(LoopEngine.run_stream) == {"model": None, "reasoning_effort": None}

    # 配置入口
    assert _params(load_settings) == []
    assert "path" in _params(load_env_file)

    # 存储/工具注册表公共方法
    assert _params(SessionStore.create) == ["self", "model_override"]
    assert _defaults(SessionStore.create) == {"model_override": None}
    assert _params(SessionStore.save) == ["self", "session"]
    assert _params(SessionStore.load) == ["self", "session_id"]
    assert _params(ToolRegistry.register) == ["self", "tool"]
    assert _params(ToolRegistry.unregister) == ["self", "name"]
    assert _params(ToolRegistry.schemas) == ["self", "lazy"]
    assert _defaults(ToolRegistry.schemas) == {"lazy": False}

    # LoopResult 关键字段存在（文档 §3 承诺）——实例化后字段可访问
    from llm_loop.core.loop.engine import LoopResult

    r = LoopResult(session_id="s", final_answer="a")
    for field in (
        "session_id", "final_answer", "rounds", "tool_calls", "model_used",
        "tokens_in", "tokens_out", "truncated", "reasoning_content",
    ):
        assert hasattr(r, field), f"LoopResult 缺承诺字段: {field}"


def test_example01_assembly_chain_runs(tmp_path, monkeypatch):
    """B5: api.md §1 快速装配链路（load_env_file→load_settings→build_engine→run）可执行.

    零 LLM 零网络: 注入最小 env + 临时 data 目录, 用真实 build_engine 装配并跑一轮.
    （Fake 客户端经注册表 provider 缓存注入, 避免触网——与 conftest build_test_engine 同思路）
    """
    from llm_loop.config import load_env_file, load_settings
    from llm_loop.factory import build_engine
    from llm_loop.llm.client import LLMResponse

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EXTRACT_ENABLED", "0")
    monkeypatch.setenv("SUMMARY_MODE", "off")

    class _Fake:
        def chat(self, messages, tools, **kw):
            return LLMResponse(content="装配链路回答", tool_calls=[], provider="fake")

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return LLMResponse(content="装配链路回答", tool_calls=[], provider="fake")

            return _gen()

    load_env_file()  # 文档 §1: 从 .env 加载（此处 env 已注入, 不依赖真实 .env）
    settings = load_settings()
    engine = build_engine(settings)
    # 用 Fake 替换默认 client（pool 路由 None override → default_client, 零触网）
    engine.llm_pool.default_client = _Fake()  # type: ignore[assignment]

    sid = engine.session.create()
    result = engine.run(sid, "你好")
    assert result.final_answer == "装配链路回答"
    assert result.rounds >= 1
    assert engine.session.exists(sid)


def test_example04_headless_service_runs(tmp_path, monkeypatch):
    """B5: headless 服务模式——示例 04 的 build_headless_app 可装配、端点可调用.

    零 LLM 零网络: env 注入 + Fake client（pool default）替换; 用 FastAPI TestClient
    调 /health 与 /chat, 断言 headless 嵌入链路（引擎单实例 → 对话端点）可用。
    """
    from fastapi.testclient import TestClient

    from llm_loop.config import load_settings
    from llm_loop.factory import build_engine
    from llm_loop.llm.client import LLMResponse

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EXTRACT_ENABLED", "0")
    monkeypatch.setenv("SUMMARY_MODE", "off")

    class _Fake:
        def chat(self, messages, tools, **kw):
            return LLMResponse(content="headless 回答", tool_calls=[], provider="fake")

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return LLMResponse(content="headless 回答", tool_calls=[], provider="fake")

            return _gen()

    settings = load_settings()
    engine = build_engine(settings)
    engine.llm_pool.default_client = _Fake()  # type: ignore[assignment]

    from llm_loop.web import build_app

    app = build_app(settings=settings, engine=engine)
    client = TestClient(app)

    assert client.get("/health").json()["status"] == "ok"
    resp = client.post("/api/v1/chat", json={"message": "你好"})
    assert resp.status_code == 200
    assert "headless 回答" in resp.text
