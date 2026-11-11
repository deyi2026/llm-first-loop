"""测试公共 fixture: FakeLLM + 隔离数据目录（design.md §2.5）.

- FakeLLM: 可编程响应序列（含流式分片模拟），不触网
- 隔离数据目录: DATA_DIR 指向 tmp_path，杜绝污染真实 ./data
- M64 全局防御: 任何指向项目真实 data 目录的 SessionStore 写盘请求 → 自动临时目录
  （兜底硬编码 data_dir="./data" 的测试，不依赖测试自觉）
"""

from __future__ import annotations

import importlib.util
import os
import platform
import re
import sys
import tempfile
import warnings
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

# ── P0-E4 S4-c: reportlab 仅 dev extra——缺失时跳过依赖它的用例文件，杜绝 collection ──
#    error（文件级 importorskip 等价形态；test_doc_image_recognition.py 不在本任务
#    写入范围，沿用上方 calib 数据同款 collect_ignore 单点跳过惯例，只影响该文件）。
_REPORTLAB_MISSING = importlib.util.find_spec("reportlab") is None  # 探测不真实 import
if _REPORTLAB_MISSING:
    collect_ignore.append("unit/test_doc_image_recognition.py")

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


# ── D3（2026-10-20 终端信号类测试偶发治理，审查修订 P1-1 改函数级粒度）：物理发信号
# （SIGTERM/SIGINT）的用例时序敏感，仅这些用例在并行门禁排除、nightly 顺序 50 次验证；
# 其余用例（含同文件内非信号用例）保持 push 门禁全覆盖（tier0 原则：门禁不降级）。
SERIAL_SIGNAL_TESTS = (
    "tests/unit/test_terminal_cli.py::test_interactive_session_propagates_sigterm_and_exits_shell",
    "tests/unit/test_terminal_cli.py::test_cli_sigterm_physically_stops_owned_execute_command",
    "tests/unit/test_terminal_cli.py::test_run_turn_real_signal_cancels_owned_generation_and_reports_process_exit",
    "tests/unit/test_terminal_cli.py::test_sigterm_during_runner_start_is_reported_as_termination_pending",
)

# Wall-clock performance assertions run alone so unrelated xdist workers cannot
# inflate the measured latency. This preserves the original acceptance limits.
SERIAL_PERF_TESTS = (
    "tests/phase5/test_m3_metrics.py::test_m3_g1_g2_metrics",
    "tests/perf/test_build_leak_detection_bench.py::test_clean_history_within_budget",
    "tests/perf/test_build_leak_detection_bench.py::test_findings_path_within_budget",
)


def pytest_collection_modifyitems(config, items):
    """tier0/serial_signal/serial_perf 单点打标（清单驱动，不侵入测试文件）."""
    tier0_marker = pytest.mark.tier0
    for item in items:
        fpath = str(item.path).replace(str(Path(__file__).resolve().parent.parent) + "/", "")
        if fpath in TIER0_FILES:
            item.add_marker(tier0_marker)
    serial_signal_marker = pytest.mark.serial_signal
    serial_perf_marker = pytest.mark.serial_perf
    for item in items:
        # 清单按函数级粒度打标；参数化用例带 [params] 后缀，故使用前缀匹配。
        nodeid = str(item.nodeid)
        if any(nodeid.startswith(entry) for entry in SERIAL_SIGNAL_TESTS):
            item.add_marker(serial_signal_marker)
        if any(nodeid.startswith(entry) for entry in SERIAL_PERF_TESTS):
            item.add_marker(serial_perf_marker)


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

# 部署泄漏隔离（批次4，2026-10-09 main+生产整合全量回归归因）：宿主生产
# runtime 可能携带 admin-once Web TaskBudget canary——env 直出
# LFL_TASK_BUDGET_WEB_CANARY_CONFIG，或经 LFL_RUNTIME_ROOT 指向的生产
# runtime.toml（task_budget_canary_config）注入。load_operator_web_canary
# 的契约是 "Absent config => default OFF"；canary 资格判定依赖 root-owned
# 配置与真实 workspace，在 tmp_path 测试工作区必然 _deny，令整批 web/engine
# 测试误报 task budget denied。隔离方式：清 env 直出键 + 把 LFL_RUNTIME_ROOT
# 指到空临时目录（resolver 找不到 runtime.toml/.env 即回退 defaults）。
# 显式传 workspace_root/config_file 的 resolver 测试与函数级
# monkeypatch.setenv("LFL_RUNTIME_ROOT", ...) 的用例不受影响。
_DEPLOYED_TASK_BUDGET_VARS = (
    "LFL_TASK_BUDGET_WEB_CANARY_CONFIG",
)

# 部署泄漏隔离（批次5，2026-10-20 B1 归因）：LFL web/execute_command 派生 shell 继承
# 部署绑定 LFL_WORKSPACE_ROOT（指向 .releases/<hash>），查询 CLI 曾把它当用户 workspace
# 选择，导致未注册硬失败或静默列出错误 workspace 的会话。queries.py 现按
# --workspace > cwd-upward > env 解析并在歧义时 exit 3；本批次剥离 ambient 值，
# 测试体内显式 setenv 的用例（monkeypatch 顺序在 fixture 之后）不受影响。
# P1-3(2026-10-25)：LFL_DEFAULT_WORKSPACE_ROOT（AI 默认可写工作区根，非身份锚）
# 同属 ambient workspace 解析面——一并剥离；isolated_data_dir 随后注入 tmp 值。
_DEPLOYED_WORKSPACE_IDENTITY_VARS = (
    "LFL_WORKSPACE_ROOT",
    "LFL_DEFAULT_WORKSPACE_ROOT",
)


# 部署泄漏隔离（批次6，2026-11-02 全量回归归因）：本机 .env/宿主 shell 导出
# LFL_SKILLS_REQUIRE_MANIFEST=1，tools_skill_files 的完整性门禁因此默认生效，
# 把测试自建的本地技能（无 manifest）判为 modified/unlisted 并隐藏，
# test_skills_loader 5 例 + test_skill_tools_p1a 2 例假红；CI 无此变量故全绿——
# 即"本机红、CI 绿"的不可移植结论。门禁本身的用例（test_skills_integrity、
# test_skill_tools_p1a 内的 setenv/delenv）在 fixture 之后执行，不受影响。
_DEPLOYED_SKILL_INTEGRITY_VARS = (
    "LFL_SKILLS_REQUIRE_MANIFEST",
)


@pytest.fixture(autouse=True)
def isolate_deployed_web_auth_env(monkeypatch, tmp_path):
    """剥离部署环境泄漏的运行时配置变量（按批次清单逐组登记）。"""
    for var in _DEPLOYED_SKILL_INTEGRITY_VARS:
        monkeypatch.delenv(var, raising=False)
    for var in _DEPLOYED_WEB_AUTH_VARS:
        monkeypatch.delenv(var, raising=False)
    for var in _DEPLOYED_COMPACT_VARS:
        monkeypatch.delenv(var, raising=False)
    for var in _DEPLOYED_PROVIDER_ADMIN_VARS:
        monkeypatch.delenv(var, raising=False)
    for var in _DEPLOYED_TASK_BUDGET_VARS:
        monkeypatch.delenv(var, raising=False)
    for key in _DEPLOYED_WORKSPACE_IDENTITY_VARS:
        monkeypatch.delenv(key, raising=False)
    # 批次4：宿主 LFL_RUNTIME_ROOT 指向生产 runtime.toml（含 canary 等生产键）；
    # 指到空临时目录使 resolver 回退 defaults。函数级 setenv 的 resolver 用例
    # 在本 fixture 之后执行，优先级不变。
    monkeypatch.setenv("LFL_RUNTIME_ROOT", str(tmp_path / "runtime-config-isolated"))


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

    # Phase5 M2（设计 §2.2.5）：可选流式通道——缺省不挂 chat_stream 属性
    # （engine getattr 拿不到 → 同步 chat，既有测试零影响）。enable_stream
    # 后实例级绑定：按 stream_config 逐 delta 产出；on_delta_n 为确定性同步
    # 钩子（在产 delta 的 next() 内回调，钩子返回即注入完成，随后同一 delta
    # 的流内检查点必然命中——消除 S17 时序 flaky，设计评审 Q4）。
    def enable_stream(self, config: dict) -> None:
        self.stream_config = config
        self.chat_stream = self._chat_stream_impl

    def _chat_stream_impl(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None = None,
        model: str | None = None,
    ):
        import time as _time
        from types import SimpleNamespace

        cfg = dict(self.stream_config or {})
        delay = float(cfg.get("delta_delay_s", 0.0) or 0.0)
        hooks = cfg.get("on_delta_n") or {}
        pieces = list(cfg.get("deltas") or [])
        # 与 chat 同源取数并记录 calls（S17-M2 断言下一轮请求历史用）；
        # generator 体在首个 next 才执行（engine 开始消费流时）。
        final_resp = self.chat(messages, tools, timeout_s=timeout_s, model=model)
        for i, piece in enumerate(pieces):
            if delay:
                _time.sleep(delay)
            hook = hooks.get(i)
            if callable(hook):
                hook(i)
            yield SimpleNamespace(text=piece)
        return final_resp


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
    # P1-3（2026-10-25，设计 §7.4）: 默认工作区根同样钉进 tmp——任何经
    # build_engine(workspace_root=None) 的测试在 _resolve_default_workspace_root
    # 解析 env 时落到 tmp_path，绝不在真实 home 建 ~/lfl-workspace（测试污染
    # 防线；与下方 chdir(tmp_path) 的旧 cwd 语义保持行为等价）。
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", str(tmp_path))
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
        # EVO-20260914-e6b8aa22: 终止 child 有界续话（与 factory 装配一致）
        from llm_loop.tools.builtin.agent_followup import AgentFollowupTool

        registry.register(AgentFollowupTool(subagent_runner))
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


# ── P0-E4 S4-a: 测试环境自证（收集前预检，pytest_configure 阶段 fail-fast）──
# 背景: 绕过入口（如直接用系统 /opt/homebrew/bin/python3 3.14）跑全量 pytest 时，
# pyproject 必装依赖缺 6 个（lark-oapi/pycryptodome/prompt-toolkit 等）→ 107 条
# collection ImportError 淹没真因。此处改为单条可执行诊断直接终止收集；
# 返回码 10 独立于 ExitCode 0-5（1=测试失败），不与"测试失败"混淆。
_ENV_PREFLIGHT_SKIP_ENV = "LFL_SKIP_ENV_PREFLIGHT"
_ENV_PREFLIGHT_EXIT_CODE = 10
_PREFLIGHT_STATUS_KEY = pytest.StashKey[str]()  # ok / skipped（header 与 junit 属性消费）

# dist 名 → 顶层 import 名真实例外表（未登记项按连字符→下划线归一推断）
_DIST_IMPORT_OVERRIDES = {
    "pycryptodome": "Crypto",
    "lark-oapi": "lark_oapi",
    "prompt-toolkit": "prompt_toolkit",
    "pyyaml": "yaml",
    "Pillow": "PIL",
    "python-multipart": "multipart",
    "wecom-aibot-python-sdk": "aibot",  # pyproject 注释: 官方 SDK 导入名 aibot
}


def _dist_import_name(dist: str) -> str:
    """dist 名 → 顶层 import 名（例外表优先，其余下划线归一）."""
    return _DIST_IMPORT_OVERRIDES.get(dist, dist.replace("-", "_"))


def _required_dist_names(pyproject_path: Path) -> list[str]:
    """读 [project].dependencies 的纯 dist 名（tomllib 只读解析，无副作用）."""
    try:
        import tomllib

        with pyproject_path.open("rb") as fh:
            specs = tomllib.load(fh).get("project", {}).get("dependencies", [])
    except Exception:  # noqa: BLE001 — 解析失败视作无约束（fail-open，预检不制造新故障）
        return []
    names: list[str] = []
    for spec in specs:
        m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(spec))
        if m:
            names.append(m.group(0))
    return names


def _find_missing_imports(dist_names: list[str]) -> list[str]:
    """find_spec 探测缺失项（不真实 import、无副作用）；返回 "dist (import 名)" 描述."""
    import importlib.util

    missing: list[str] = []
    for dist in dist_names:
        name = _dist_import_name(dist)
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(f"{dist} (import {name})")
    return missing


def _measure_venv_version(venv_python: Path) -> str:
    """实测期望解释器版本（只读子进程探测；失败 fail-open 返回占位）."""
    try:
        import subprocess

        r = subprocess.run(
            [str(venv_python), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _env_preflight_diagnostic(missing: list[str]) -> str:
    """单条诊断: 一次列全缺失模块 + 当前/期望解释器（含实测版本）+ 可粘贴修复命令."""
    venv_python = _PROJECT_ROOT / ".venv" / "bin" / "python"
    venv_ver = _measure_venv_version(venv_python) if venv_python.exists() else "(.venv 不存在)"
    fix_cmd = f"cd {_PROJECT_ROOT} && .venv/bin/python -m pytest <测试参数>"
    return "\n".join([
        "LFL 测试环境预检失败: 当前解释器缺少 pyproject [project].dependencies 必装依赖，"
        "继续将产生大量 collection ImportError；请改用仓库 .venv 解释器。",
        "reason_code=env_missing_dependency",
        f"缺失模块({len(missing)}): " + ", ".join(sorted(missing)),
        f"当前解释器: {sys.executable} ({platform.python_version()})",
        f"期望解释器: {venv_python} (实测版本 {venv_ver})",
        f"修复命令: {fix_cmd}",
        f"逃生阀: {_ENV_PREFLIGHT_SKIP_ENV}=1 跳过预检（自担风险）",
    ])


def _run_env_preflight() -> str:
    """S4-a 主流程: 缺依赖→单条诊断终止；齐全但非 .venv→仅告警；返回 ok/skipped.

    - 预检自身无副作用: find_spec 不真实 import，tomllib 只读，venv 版本探测为
      只读子进程；不写任何文件。
    - .venv 目录不存在（如 CI）时不发 prefix 告警——不存在"期望解释器"，
      避免干净环境噪音；依赖缺失检查不受此影响。
    """
    if os.environ.get(_ENV_PREFLIGHT_SKIP_ENV) == "1":
        return "skipped"
    missing = _find_missing_imports(_required_dist_names(_PROJECT_ROOT / "pyproject.toml"))
    if missing:
        pytest.exit(_env_preflight_diagnostic(missing), returncode=_ENV_PREFLIGHT_EXIT_CODE)
        return "exited"  # pragma: no cover — pytest.exit 必抛 Exit，不可达
    venv_dir = (_PROJECT_ROOT / ".venv").resolve()
    if venv_dir.exists() and Path(sys.prefix).resolve() != venv_dir:
        warnings.warn(
            "LFL 环境预检: 必装依赖齐全但解释器非仓库 .venv（当前 prefix "
            f"{sys.prefix}，期望 {venv_dir}）；单文件调试可继续，全量跑建议 "
            ".venv/bin/python -m pytest",
            pytest.PytestWarning,
            stacklevel=2,
        )
    return "ok"


def _llm_loop_source() -> str:
    """llm_loop 实际解析来源目录（find_spec 取 spec，不执行模块代码、无副作用）.

    宿主 shell 可能 PYTHONPATH 钉住旧 release 快照（.releases/<hash>/src）——裸
    `python -c` 读到 stale code；pytest 靠 pyproject pythonpath=["src"]（相对
    rootdir 前插）才测工作树。指纹必须记录实测来源，供事后判定"这次测的是哪棵树"。
    """
    try:
        spec = importlib.util.find_spec("llm_loop")
        locations = list(getattr(spec, "submodule_search_locations", None) or [])
        if locations:
            return str(Path(locations[0]).resolve())
        if spec is not None and spec.origin:
            return str(Path(spec.origin).resolve())
    except (ImportError, ValueError):
        pass
    return "unknown"


def _check_llm_loop_source(config) -> None:
    """llm_loop 导入来源不在 rootdir 之下 → warning（不阻塞），文案带双路径.

    树错配比缺依赖更隐蔽（测试全绿但测的是旧快照）；只告警不阻断——
    镜像仓库间互测等合法场景仍可继续跑。
    """
    source = _llm_loop_source()
    if source == "unknown":
        return
    try:
        inside = Path(source).is_relative_to(_PROJECT_ROOT)
    except (OSError, ValueError):
        inside = False
    if inside:
        return
    msg = (
        f"LFL 环境自证: llm_loop 实际导入来源 {source} 不在当前仓库 rootdir "
        f"{_PROJECT_ROOT} 之下——本次测试可能测的是另一棵树（如 .releases 快照）；"
        "建议在仓库根目录用 .venv/bin/python -m pytest 运行"
    )
    try:  # 优先 pytest 官方 config 期告警通道（进 warnings summary）
        config.issue_config_time_warning(pytest.PytestWarning(msg), stacklevel=2)
    except AttributeError:  # 旧版 pytest 无该 API → 原生 warning 兜底
        warnings.warn(pytest.PytestWarning(msg), stacklevel=3)


# ── EVO-20260811-f1e43351: 测试副作用审计（pytest 启动时 fail-open 告警，不阻断）──
def pytest_configure(config):
    """P0-E4 S4-a 环境预检 + 树来源自证（warning 级）+ 副作用审计（fail-open 告警）."""
    config.stash[_PREFLIGHT_STATUS_KEY] = _run_env_preflight()
    _check_llm_loop_source(config)
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


# ── P0-E4 S4-b: 环境指纹（报告头 + junit testsuite 属性）──
def _dependency_version_summary() -> list[str]:
    """依赖版本摘要（importlib.metadata 读 dist 元数据，不 import 被测依赖）."""
    import importlib.metadata as importlib_metadata

    parts: list[str] = []
    for dist in _required_dist_names(_PROJECT_ROOT / "pyproject.toml"):
        try:
            parts.append(f"{dist}=={importlib_metadata.version(dist)}")
        except Exception:  # noqa: BLE001 — 单项读不到不拖垮指纹
            parts.append(f"{dist}==missing")
    return parts


def pytest_report_header(config):
    """S4-b 环境指纹: 解释器路径/版本 + preflight 状态标注 + 依赖版本摘要 + llm_loop 来源."""
    status = config.stash.get(_PREFLIGHT_STATUS_KEY, "unknown")
    lines = [
        f"LFL env preflight: preflight={status} interpreter={sys.executable} "
        f"python={platform.python_version()}"
    ]
    if status == "skipped":
        lines.append(f"LFL env preflight: {_ENV_PREFLIGHT_SKIP_ENV}=1 逃生阀生效，依赖未校验")
    else:
        lines.append("LFL env deps: " + ", ".join(_dependency_version_summary()))
    if _REPORTLAB_MISSING:
        lines.append(
            "LFL env note: reportlab 缺失（dev extra）→ 已跳过 unit/test_doc_image_recognition.py（S4-c）"
        )
    lines.append(f"LFL env source: llm_loop source={_llm_loop_source()}")
    return lines


def _env_fingerprint_properties(status: str) -> list[tuple[str, str]]:
    """S4-b junit testsuite 属性集（名, 值）；内容面纯函数，便于单测锁定."""
    props: list[tuple[str, str]] = [
        ("lfl_env_preflight", status),
        ("lfl_env_interpreter", sys.executable),
        ("lfl_env_python", platform.python_version()),
        ("lfl_env_llm_loop_source", _llm_loop_source()),
    ]
    for item in _dependency_version_summary():
        dist, _, version = item.partition("==")
        props.append((f"lfl_env_dep.{dist}", version))
    return props


@pytest.fixture(scope="session", autouse=True)
def _env_fingerprint_junit(request):
    """S4-b: 环境指纹写入 junit testsuite 属性.

    选型: record_testsuite_property 是 pytest 官方 session 级 fixture（junitxml
    插件提供；未启用 --junitxml 时自动 no-op），不触碰 junitxml 内部 API /
    config 私有 stash。已知限制（官方文档声明）: 与 pytest-xdist 不兼容时
    属性可能缺失——junit 属性为尽力而为通道，终端 header 指纹不受影响。
    """
    try:
        record = request.getfixturevalue("record_testsuite_property")
    except pytest.FixtureLookupError:
        return
    for name, value in _env_fingerprint_properties(
        request.config.stash.get(_PREFLIGHT_STATUS_KEY, "unknown")
    ):
        record(name, value)
