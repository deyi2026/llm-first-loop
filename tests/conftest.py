"""测试公共 fixture: FakeLLM + 隔离数据目录（design.md §2.5）.

- FakeLLM: 可编程响应序列（含流式分片模拟），不触网
- 隔离数据目录: DATA_DIR 指向 tmp_path，杜绝污染真实 ./data
- M64 全局防御: 任何指向项目真实 data 目录的 SessionStore 写盘请求 → 自动临时目录
  （兜底硬编码 data_dir="./data" 的测试，不依赖测试自觉）
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse

# ── M64 测试环境污染全局防御（pytest 收集前执行）──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REAL_DATA_DIR = str((_PROJECT_ROOT / "data").resolve())

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _isolate_real_data_dir(data_dir):
    """测试环境兜底：指向项目真实 data 目录的目录 → 独立临时目录（零污染）.

    - "./data" / "data" / 项目 data 绝对路径 → 重定向
    - 其余（tmp_path 等）原样保留（不影响测试预期目录）
    """
    if data_dir is None:
        return data_dir
    try:
        d = str(data_dir)
        if d in ("./data", "data"):
            return tempfile.mkdtemp(prefix="llm-test-data-")
        if str((_PROJECT_ROOT / d).resolve()) == _REAL_DATA_DIR:
            return tempfile.mkdtemp(prefix="llm-test-data-")
    except Exception:  # noqa: BLE001 — 防御逻辑失败保持原值（fail-open）
        pass
    return data_dir


def _patch_session_store_isolation():
    """替换 SessionStore.__init__：所有写盘请求经 _isolate_real_data_dir 兜底."""
    from llm_loop.core.session import SessionStore

    _orig_init = SessionStore.__init__

    def _isolated_init(self, data_dir, *args, **kwargs):
        _orig_init(self, _isolate_real_data_dir(data_dir), *args, **kwargs)

    SessionStore.__init__ = _isolated_init  # type: ignore[method-assign]


_patch_session_store_isolation()


class FakeLLM:
    """可编程 LLM 桩：按预编程响应序列依次返回.

    记录每次调用收到的 messages/tools（供测试断言）。
    响应项: {"content": str, "tool_calls": [ToolCall]} 或 callable(history) -> LLMResponse
    """

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []  # 每次调用的 messages/tools 记录
        self.max_tokens: int | None = None
        self.wire_protocol: str = "openai"  # P3-5 对齐 LLMClient 新字段  # 2026-08-15: 对齐 LLMClient 新装配字段（pool 继承默认 client 预算）

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "model": model})
        if not self._responses:
            return LLMResponse(content="（无更多响应）", tool_calls=[], provider="fake")
        item = self._responses.pop(0)
        if callable(item):
            result = item(self.calls)
            assert isinstance(result, LLMResponse)
            return result
        if isinstance(item, LLMResponse):
            return item
        content = item.get("content")
        tcs = item.get("tool_calls") or []
        # M20 THK-04: FakeLLM 响应项支持 reasoning_content（多轮回传断言用）
        return LLMResponse(
            content=content,
            tool_calls=tcs,
            provider="fake",
            reasoning_content=item.get("reasoning_content"),
        )

    @staticmethod
    def tool(name: str, arguments: dict, tc_id: str = "call_fake_1") -> ToolCall:
        return ToolCall(id=tc_id, name=name, arguments=arguments)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """隔离数据目录：所有测试不触碰真实 ./data.

    EVO-20260817-38364821（已 accepted）: 同时覆盖 LFL_DATA_DIR——
    interop 写方（job 终态通知 _notify_completion / subagent_report inbox）读
    os.environ.get("LFL_DATA_DIR", "data")，缺省回落项目真实 data/ 造成污染
    （2026-08-17 实测 10 条 job 通知混入真实 inbox）。
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("LFL_DATA_DIR", str(data_dir))
    return data_dir


@pytest.fixture
def fake_settings(isolated_data_dir):
    """测试用 Settings（Fake key/base_url/model + 隔离 DATA_DIR）."""
    from llm_loop.config import Settings

    return Settings(
        llm_api_key="test-key",
        llm_base_url="https://fake.local/v1",
        llm_model="fake-model",
        data_dir=str(isolated_data_dir),
        max_iterations=10,
    )


def __build_test_pool(fake, fake_settings):
    """M48（design §5.3）: 测试用 ModelClientPool（FakeLLM 作 default_client, duck typing）.

    Pool 仅作为路由容器；测试场景不实际走 provider 级 LLMClient（仍是 FakeLLM）.
    默认 L0 合成注册表（仅含 fake_settings.llm_model）,保证零回归.
    M49（design §5.4）: 传递 model_fallbacks_raw（默认空, 单元测试 fallback 行为时单独构造 pool）.
    M50 修复: 预置 _provider_cache 为 FakeLLM —— per-call 模型解析成功后路由返回 fake,
    避免测试环境构造真实 LLMClient 触网.
    """
    from llm_loop.llm.pool import ModelClientPool
    from llm_loop.llm.providers import load_registry

    registry = load_registry(fake_settings)
    pool = ModelClientPool(  # type: ignore[arg-type]
        registry=registry,
        default_client=fake,
        model_fallbacks_raw=fake_settings.model_fallbacks_raw,
    )
    for pid in registry.providers:
        pool._provider_cache[pid] = fake  # noqa: SLF001 — 测试预置缓存，避免触网
    return pool


@pytest.fixture
def build_test_engine(fake_settings):
    """构造测试引擎（装配 FakeLLM 与隔离存储），返回 (engine, fake_llm)."""

    def _build(responses: list[Any]):
        from llm_loop.core.loop import LoopEngine
        from llm_loop.core.session import SessionStore
        from llm_loop.feedback.validator import DeclarationValidator
        from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
        from llm_loop.introspection.status import ArchitectureStatusProvider
        from llm_loop.memory.archive import ArchiveStore
        from llm_loop.memory.store import MemoryStore
        from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
        from llm_loop.tools.builtin.read_file import ReadFileTool
        from llm_loop.tools.registry import ToolRegistry

        fake = FakeLLM(responses)
        memory = MemoryStore(fake_settings.memory_dir)
        session = SessionStore(fake_settings.sessions_dir)
        archive = ArchiveStore(fake_settings.archive_dir) if fake_settings.archive_enabled else None
        registry = ToolRegistry(
            tool_timeout_s=fake_settings.tool_timeout_s,
            max_output_chars=fake_settings.tool_max_output_chars,
            archive_store=archive,
        )
        registry.register(ReadFileTool())
        registry.register(ExecuteCommandTool())
        # EVO 第五项: 递归子代理（与 factory 装配一致，测试真实路径）
        from llm_loop.subagent.runner import SubAgentRunner
        from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

        subagent_runner = SubAgentRunner(
            llm=fake, registry=registry, session_store=session
        )
        registry.register(SpawnSubAgentTool(subagent_runner))
        # DSH 借鉴 022-B: 子代理中途报告（与 factory 装配一致）
        from llm_loop.tools.builtin.subagent_report import SubagentReportTool

        registry.register(SubagentReportTool())
        status = ArchitectureStatusProvider(
            audit_dir=fake_settings.audit_dir,
            enabled=fake_settings.self_inspection_enabled,
            config_status=fake_settings.to_status_dict,
        )
        ctx = CorrectionContext()
        corrections = CorrectionToolRegistry(
            ctx, audit_dir=fake_settings.audit_dir, status_provider=status, archive_store=archive
        )
        from llm_loop.factory import _CorrectionAdapterTool
        from llm_loop.introspection.search import RecordSearcher

        searcher = RecordSearcher(
            audit_dir=fake_settings.audit_dir, memory_store=memory, archive_store=archive
        )
        corrections._search_records_fn = lambda **kw: searcher.search(**kw)  # noqa: SLF001

        for td in corrections.tool_defs():
            registry.register(
                _CorrectionAdapterTool(
                    corrections,
                    name=td["name"],
                    description=td["description"],
                    parameters=td["parameters"],
                )
            )
        validator = DeclarationValidator(audit_dir=fake_settings.audit_dir)
        # M12 组件装配
        from llm_loop.core.runtime_params import RuntimeParams
        from llm_loop.feedback.fault_classifier import FaultClassifier
        from llm_loop.feedback.selfheal_budget import SelfHealBudget
        from llm_loop.introspection.evolution import EvolutionStore

        runtime = RuntimeParams(fake_settings, strategy=ctx.strategy)
        runtime.set_persist_path(fake_settings.audit_dir / "param_adjust_history.jsonl")
        runtime.set_max_adjust_per_round(fake_settings.param_adjust_per_round)
        ctx.runtime = runtime
        ctx.evolution_store = EvolutionStore(fake_settings.audit_dir)
        # M17 FR-REVIEW-AI-02/03: LoopSignalDetector 三合一（executing 提醒检测数据源）
        from llm_loop.introspection.loop_signals import LoopSignalDetector

        loop_signal_detector = LoopSignalDetector(
            eval_trigger_detector=None,
            status=status,
            settings=fake_settings,
        )
        engine = LoopEngine(
            llm_client=fake,  # type: ignore[arg-type] — FakeLLM 实现 chat 协议（Duck typing）
            registry=registry,
            memory=memory,
            session=session,
            settings=fake_settings,
            validator=validator,
            status_provider=status,
            correction_registry=corrections,
            correction_ctx=ctx,
            archive=archive,
            runtime=runtime,
            fault_classifier=FaultClassifier(),
            selfheal_budget=SelfHealBudget(
                max_attempts=fake_settings.selfheal_max_attempts,
                max_per_round=fake_settings.selfheal_max_per_round,
            ),
            evolution_store=ctx.evolution_store,
            loop_signal_detector=loop_signal_detector,
            # M48（design §5.3）: 测试路径注入 ModelClientPool（FakeLLM 作 default_client，
            # pool.get_client(None) → fake；override 路径仅在 test_model_tools 显式构造）
            llm_pool=__build_test_pool(fake, fake_settings),
        )
        return engine, fake

    return _build


# ── EVO-20260811-f1e43351: 测试副作用审计（pytest 收集后自动检查，告警不阻断）──
def pytest_collection_finish(session):
    """收集完成时跑测试副作用审计；仅告警不阻断（--strict 语义由脚本自身控制）。

    复用 scripts/audit_test_side_effects.py 的审计逻辑；跳过即视为已隔离。
    默认告警不阻断（与脚本 exit 0 一致）；需阻断可在 .env 设 TEST_SIDE_EFFECT_AUDIT_STRICT=1。
    """
    import os
    import subprocess
    import sys

    if os.environ.get("TEST_SIDE_EFFECT_AUDIT", "1") == "0":
        return
    script = Path(__file__).resolve().parent.parent / "scripts" / "audit_test_side_effects.py"
    if not script.exists():
        return
    strict = os.environ.get("TEST_SIDE_EFFECT_AUDIT_STRICT", "0") == "1"
    cmd = [sys.executable, str(script)] + (["--strict"] if strict else [])
    try:
        subprocess.run(cmd, cwd=script.parent.parent, timeout=30)
    except Exception:  # noqa: BLE001 — 审计失败不阻断测试
        pass
