"""测试公共 fixture: FakeLLM + 隔离数据目录（design.md §2.5）.

- FakeLLM: 可编程响应序列（含流式分片模拟），不触网
- 隔离数据目录: DATA_DIR 指向 tmp_path，杜绝污染真实 ./data
- M64 全局防御: 任何指向项目真实 data 目录的 SessionStore 写盘请求 → 自动临时目录
  （兜底硬编码 data_dir="./data" 的测试，不依赖测试自觉）
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse

# ── calib/screening 系测试依赖 data/calib/*.json 运行时数据（.gitignore 设计不入库）──
# CI checkout 无 data/ 时整体跳过收集，避免 collection error / FileNotFoundError；
# 本地有数据则照常收集执行（并入 origin/main b4eb4f8/45f7631 方案的推广版）。
_CALIB_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "calib"
collect_ignore: list[str] = []
if not _CALIB_DATA_DIR.exists():
    _unit_dir = Path(__file__).resolve().parent / "unit"
    collect_ignore = [
        str(p.relative_to(Path(__file__).resolve().parent))
        for p in sorted(_unit_dir.glob("test_calib_*.py"))
    ]
    if (_unit_dir / "test_screening_s_runner.py").exists():
        collect_ignore.append("unit/test_screening_s_runner.py")

# ── R9-WF-01 tier0 冒烟集（T9-A 四类准入；标注口径：conftest 路径清单单点打标，──
#    不侵入测试文件——外部混合层避让约束下的必然选择；Phase 2 守卫就绪后
#    test_arch_guards.py（四检测器全集类）入列）
TIER0_FILES = (
    # ⑤ R9 结构守卫全集（三层红线/棘轮/import/cycle——B2-P2-08，T9-A ②）
    "tests/unit/test_arch_guards.py",
    # ① 六门与开关锚点（行为基线哨兵）
    "tests/unit/test_r824_final_gates.py",
    "tests/unit/test_runtime_zero_prompt.py",
    "tests/unit/test_runtime_zero_prompt_static.py",
    "tests/unit/test_latent_channel_exit.py",
    "tests/unit/test_tool_result_factualization.py",
    "tests/unit/test_cache_block_reclassification.py",
    # ③ wire 契约（等价性证明面；tail packet 系列）
    "tests/unit/test_wire_fixtures.py",
    "tests/unit/test_reasoning_tail.py",
    # ④ core 回路冒烟：五故障场景承载
    "tests/unit/test_err1210_recovery.py",
    "tests/unit/test_loop_stagnation.py",
    "tests/unit/test_interruption_recovery_r819.py",
    "tests/unit/test_fail_open_recovery.py",
    # ④ core 回路冒烟：engine/build/history/factory 核心单测子集（按文件不拆用例）
    "tests/unit/test_engine_cancel_llm_error_isolation.py",
    "tests/unit/test_engine_reentrancy.py",
    "tests/unit/test_factory.py",
    "tests/unit/test_history.py",
    "tests/unit/test_history_layering.py",
)


def pytest_collection_modifyitems(config, items):
    """tier0 单点打标（路径清单驱动，不侵入测试文件）."""
    tier0_marker = pytest.mark.tier0
    for item in items:
        fpath = str(item.path).replace(str(Path(__file__).resolve().parent.parent) + "/", "")
        if fpath in TIER0_FILES:
            item.add_marker(tier0_marker)


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


@pytest.fixture(autouse=True)
def isolate_process_environment():
    """每个测试后恢复完整进程环境，阻断未走 monkeypatch 的跨测试污染。

    `load_env_file()` 是生产入口，按设计会直接向 ``os.environ`` 写入缺失键。
    测试若直接调用它，pytest 的 ``monkeypatch`` 无法自动回滚由函数内部新增的
    其他键。环境恢复属于测试沙箱边界，不改变生产配置加载语义。
    """
    before = os.environ.copy()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(before)


# 部署泄漏隔离（2026-09-09 全量回归归因）：在 LFL web 部署环境内跑 pytest 时，
# 进程继承 WEB_AUTH_REQUIRE=1 / WEB_ORIGIN_ALLOWLIST 等生产暴露变量；
# auth_required() 请求期读 env，任一非空即"鉴权已启用"，配合无 key/hash
# 触发 fail-closed 503，令未显式配置鉴权的 web 测试假红（CI/干净环境无此
# 变量，origin/main 全绿即证明无测试依赖该泄漏）。测试体内显式 setenv 的
# 用例在 fixture 之后执行，不受影响。
_DEPLOYED_WEB_AUTH_VARS = (
    "WEB_AUTH_REQUIRE",
    "WEB_ORIGIN_ALLOWLIST",
    "WEB_API_KEY",
    "WEB_LOGIN_PASSWORD_HASH",
)

# 部署泄漏隔离（2026-09-09 全量回归归因批次2）：LFL 运行环境导出
# COMPRESS_TARGET_RATIO=0.5 / APPEND_COMPRESSION=1 / COMPACT_RATIO=0.85，
# history.py _compress_target_ratio() 直接读 os.environ，泄漏令
# archive_target_ratio 断言（0.6 默认）假红；COMPACT_RATIO 泄漏同源
# （部分测试模块已自带 monkeypatch 钉值，此处于全局兜底，测试体内
# setenv 优先级不变）。
_DEPLOYED_COMPACT_VARS = (
    "COMPRESS_TARGET_RATIO",
    "APPEND_COMPRESSION",
    "COMPACT_RATIO",
)

# 部署泄漏隔离（批次3，2026-09-09 provider admin 全量回归归因）：LFL 运行
# 外壳导出 LLM_MODEL（如 default provider 路由）。provider_admin 端点对
# 来自进程外部环境的 LLM_MODEL 按"外部属主"保护返回 409，MODEL_PROVIDERS
# 存在时控制面整体只读；两者泄漏令默认模型持久化用例假红（409 != 200）。
# 测试体内显式 setenv 的用例（如只读模式、外部属主 409 用例）在 fixture
# 之后执行，不受影响。
_DEPLOYED_PROVIDER_ADMIN_VARS = (
    "LLM_MODEL",
    "MODEL_PROVIDERS",
)


@pytest.fixture(autouse=True)
def isolate_deployed_web_auth_env(monkeypatch):
    """剥离部署环境泄漏的运行时配置变量（按批次清单逐组登记）。"""
    for var in _DEPLOYED_WEB_AUTH_VARS:
        monkeypatch.delenv(var, raising=False)
    for var in _DEPLOYED_COMPACT_VARS:
        monkeypatch.delenv(var, raising=False)
    for var in _DEPLOYED_PROVIDER_ADMIN_VARS:
        monkeypatch.delenv(var, raising=False)


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
    interop 写方（如 job 终态通知 _notify_completion）读取
    os.environ.get("LFL_DATA_DIR", "data")，缺省回落项目真实 data/ 造成污染
    （2026-08-17 实测 10 条 job 通知混入真实 inbox）。
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("LFL_DATA_DIR", str(data_dir))
    # R9-IMM-02（D6 双修·测试面纵深防御）: cwd 锁进沙箱——任何残余相对路径写入
    # （含 path_registry 曾静默回落 "data/" 的洞）都落在 tmp 而非真实仓库 data/。
    # 与生产面 fallback 抛错独立成立。
    monkeypatch.chdir(tmp_path)
    return data_dir


@pytest.fixture(autouse=True)
def guard_mode_observe_default(monkeypatch):
    """R8.24-D DT-1.5: guard default 已切 enforce（fail-closed，生产缺省）.

    测试基建统一显式覆盖为 observe（operator 显式覆盖通道的合法使用——生产
    default enforce 下无凭据 user 写入 drop，而存量测试大量不带 ingress 调用
    engine.run）。fail-closed 专项断言（无 env 时 default==enforce、无凭据
    drop、有凭据放行）在 tests/unit/test_trace_leak_quarantine.py 内显式
    monkeypatch.delenv 验证，不受本覆盖影响。
    """
    monkeypatch.setenv("LFL_LEAK_GUARD_MODE", "observe")


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
        # EVO-20260819-2254e3b4 方案B 适配: 测试环境关闭"回答末尾常态展示缓存命中率"
        # （FakeLLM 无真实缓存数据，尾注会破坏 web 协议精确断言；功能本身由
        # test_cache_monitor.py::test_format_health_note_* 专项覆盖，真实运行默认 True 不受影响）
        cache_hit_show_in_answer=False,
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
        registry.add_session_cancel_hook(subagent_runner.cancel_parent)
        registry.add_async_obligation_hook(subagent_runner.pending_obligations)
        registry.register(SpawnSubAgentTool(subagent_runner))
        from llm_loop.tools.builtin.agent_message import AgentMessageTool
        from llm_loop.tools.builtin.subagent_result import SubAgentResultTool

        registry.register(AgentMessageTool(subagent_runner))
        registry.register(SubAgentResultTool(subagent_runner))
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
        # Operator-only pending-review helper; ordinary model loop does not scan it.
        from llm_loop.introspection.loop_signals import LoopSignalDetector

        loop_signal_detector = LoopSignalDetector()
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
            loop_signal_detector=loop_signal_detector,
            # M48（design §5.3）: 测试路径注入 ModelClientPool（FakeLLM 作 default_client，
            # pool.get_client(None) → fake；override 路径仅在 test_model_tools 显式构造）
            llm_pool=__build_test_pool(fake, fake_settings),
        )
        return engine, fake

    return _build


# ── EVO-20260811-f1e43351: 测试副作用审计（pytest 启动时 fail-open 告警，不阻断）──
def pytest_configure(config):
    """扫描 tests/ 未 Mock 的真实副作用高风险特征，仅告警不阻断."""
    try:
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent
        script = root.parent / "scripts" / "audit_test_side_effects.py"
        if script.exists():
            r = subprocess.run(
                [sys.executable, str(script), str(root)],
                capture_output=True, text=True, timeout=30,
            )
            out = (r.stdout or "").strip()
            if out:
                print(out, file=sys.stderr)
    except Exception:  # noqa: BLE001 — fail-open，审计异常绝不阻断 pytest
        pass
