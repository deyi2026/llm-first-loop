"""LLM-First Core Loop 配置（环境变量集中读取与校验）.

设计: design.md §2.4.1 — 密钥仅从环境变量读取（DFX-SEC-02），
不写入任何 JSON/日志；`.env.example` 提供模板。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigFallbackNote:
    """配置项非法值回退标注（不含 raw 原文，防密钥经日志扩散）."""

    config_name: str
    fallback_value: Any
    invalid_value_type: str


_fallback_notes: list[ConfigFallbackNote] = []


def _note_invalid_fallback(name: str, fallback_value: Any, invalid_value_type: str) -> None:
    """记录配置项非法值回退（仅配置项名 + 回退结果 + 类型描述，不回显原始非法值）."""
    _fallback_notes.append(ConfigFallbackNote(name, fallback_value, invalid_value_type))
    logger.warning("配置项 %s 值非法（%s），已回退默认值 %r", name, invalid_value_type, fallback_value)


def _raw_env(name: str) -> str:
    """读取环境变量并剥离行内注释（与 load_env_file EVO-ba4a107c 对齐）.

    防外层 shell 残留脏值（如 RETRIEVE_TIMEOUT_S="1  # 注释"）导致解析失败回退默认：
    环境变量优先原则下 .env 无法覆盖已存在的脏值，解析函数自身剥离注释兜底。
    """
    if name in os.environ:
        raw = os.environ[name]
        if " #" in raw:
            raw = raw.split(" #", 1)[0]
        return raw
    return ""


def _env_int(name: str, default: int) -> int:
    raw = _raw_env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _note_invalid_fallback(name, default, "非整数字符串")
        return default


def load_env_file(path: str | Path | None = None) -> None:
    """从 .env 加载配置到环境变量（M63 配置加载统一，环境变量优先）.

    供 CLI 等非 restart_system.sh 管理的入口在 load_settings 前调用，保证与
    web/feishu 进程（restart_system.sh 已注入 .env）配置一致。

    - 已设置的环境变量不被覆盖（环境优先）
    - 忽略 # 注释与空行；值首尾单/双引号剥离
    - 文件不存在 / 读取失败 fail-open（不阻断启动）
    """
    if path is None:
        path = Path(__file__).resolve().parent.parent.parent / ".env"
    p = Path(path)
    if not p.exists():
        return
    try:
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if not key or not key.isidentifier():
                continue
            if key in os.environ:
                continue  # 环境变量优先，已设置的键不覆盖
            val = val.strip()
            # 行内注释剥离（EVO-20260813-ba4a107c）: 值与 # 之间的空白分隔处截断，
            # 避免 `KEY=1  # 注释` 把注释带进值导致 _env_int 解析失败回退默认
            val = val.split(" #", 1)[0].strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            os.environ[key] = val
    except OSError:
        pass  # 读取失败 fail-open


def _env_bool(name: str, default: bool) -> bool:
    raw = _raw_env(name).strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    _note_invalid_fallback(name, False, "非布尔字符串")
    return False


def _env_thinking_mode(name: str) -> bool:
    """LLM_THINKING_MODE 解析: enabled/1/true/on → True；disabled/0/false/off → False；非法回退 True."""
    raw = _raw_env(name).strip().lower()
    if not raw:
        return True  # 未设置默认 enabled
    if raw in {"enabled", "1", "true", "on", "yes"}:
        return True
    if raw in {"disabled", "0", "false", "off", "no"}:
        return False
    _note_invalid_fallback(name, True, "非布尔字符串")
    return True


def _env_effort(name: str) -> str:
    """LLM_REASONING_EFFORT 解析: low/high/max；非法回退 high."""
    raw = _raw_env(name).strip().lower()
    if raw in {"low", "high", "max"}:
        return raw
    if raw:
        _note_invalid_fallback(name, "high", "非 low/high/max 字符串")
    return "high"


def _env_evolve_level(name: str) -> int:
    """EVOLVE_LOCAL_EXEC 三级解析（0/1/2；旧布尔 true/false 映射 1/0；非法回退 0）."""
    raw = _raw_env(name).strip().lower()
    if raw in {"0", "1", "2"}:
        return int(raw)
    if raw in {"true", "yes", "on", "1"}:
        return 1
    if raw in {"false", "no", "off", "0"}:
        return 0
    if raw:
        _note_invalid_fallback(name, 0, "非 0/1/2 或布尔字符串")
    return 0


def _env_exec_mode(name: str) -> str:
    """EXEC_MODE 解析: readonly/allowlist/blocked；未设置返回空（不启用分级）；非法回退 blocked（安全优先）."""
    raw = _raw_env(name).strip().lower()
    if not raw:
        return ""  # 未设置 = 不启用分级（AI 可执行 shell，仅灾难性硬阻断）
    if raw in {"readonly", "allowlist", "blocked"}:
        return raw
    _note_invalid_fallback(name, "blocked", "非 readonly/allowlist/blocked 字符串")
    return "blocked"


def _env_run_mode(name: str) -> str:
    """RUN_MODE 运行模式解析（EVO-20260814 P1-A，对齐 Harness 四种运行模式）.

    standard: 全工具集（默认，零回归）
    ptc:      程序化工具调用强化（对齐 Harness PTC 模式）——全工具集但命令执行为
              主路径（web 类工具默认降级禁用，减少 LLM 在低效 web 检索上的往返）
    minimal:  精简工具集——只读 + 必要执行（web/飞书/playwright 等外围工具禁用）
    creative: 宽松默认参数——更大超时/输出阈值/检索上限（对齐 Harness creative 模式）
    非法回退 standard（不阻断启动，安全性不受影响）。
    """
    raw = _raw_env(name).strip().lower()
    if not raw:
        return "standard"
    if raw in {"standard", "ptc", "minimal", "creative"}:
        return raw
    _note_invalid_fallback(name, "standard", "非 standard/ptc/minimal/creative 字符串")
    return "standard"


def _count_fallbacks(raw: str) -> int:
    """MODEL_FALLBACKS 计数（仅统计非空逗号分隔项，非法判定由 pool.fallback_candidates 完成）.

    to_status_dict 暴露此计数的目的: AI 可经 architecture_status 自查"是否配置了降级链"，
    但**不暴露降级链明细**（provider/model 引用集合不外泄，密钥安全 DFX-SEC-02 + 设计原则 4）。
    """
    if not raw:
        return 0
    return sum(1 for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """集中配置面：全部运行参数从环境变量装配（design.md §2.4.1）."""

    # ── LLM API（必填）──
    llm_api_key: str
    llm_base_url: str
    llm_model: str

    # ── 循环控制 ──
    # R10(2026-08-14): 默认 20→40——多步任务（读→改→验证→再改）实测常超 20 轮触顶；
    # 仍受 adjust_strategy 硬上限 500 约束；80% 轮数时程序注入 [轮数预警]（AI 可自主调大）
    max_iterations: int = 40
    llm_timeout_s: float = 120.0

    # ── 数据目录 ──
    data_dir: str = "./data"
    # ── D1 事件日志（单一真相源，design.md §2.2.1）──
    # 关闭时事件写入零行为零回归（读路径/既有写路径不受影响）
    event_log_enabled: bool = True
    # EVENT_LOGS_DIR 覆盖（空 = 从 data_dir 派生 event_logs_dir）
    event_logs_dir_override: str = ""
    # ── D1 后续批次 2：读路径切换（退役阶段，design.md §2.4.1）──
    # session_json（默认）= 既有 load 读 session JSON（零回归）
    # event_log = 从事件日志 replay 重建（退役后切换）
    read_path_source: str = "session_json"
    # ── D1 后续批次 3：事件日志滚动策略（design.md §2.4.1）──
    event_log_rotate_bytes: int = 10 * 1024 * 1024  # 0=禁用大小触发
    event_log_rotate_days: int = 30  # 0=禁用天数触发
    event_log_rotate_on_session_end: bool = True
    # ── D1 后续批次 4：pre-step 过滤钩子（design.md §2.4.1）──
    event_hooks_config: str = ""  # 钩子规则配置文件路径（空=钩子链默认空零行为）

    # ── 工具 ──
    tool_timeout_s: float = 60.0
    tool_max_output_chars: int = 100000
    # EVO-20260811-22a7d3e1: 工具输出分层注入阈值（超过则默认注入首/尾摘要，原文另存可检索）
    tool_summary_threshold: int = 12000  # 2026-08-15 放大字数（5000→12000；截断信号强化批次）
    # EVO-20260811-7baa2737: 历史分层降级（旧长 tool 消息降级为摘要，原文归档）
    tool_trim_enabled: bool = True
    # R3: tool_trim 自适应降级年龄（0=自适应：按占用率自动调 <40%→20/40-70%→10/>70%→5；>0=固定值禁用自适应）
    tool_trim_age: int = 0  # auto-adaptive (existing): 0=按占用率自适应
    # EVO-A: tool_trim 降级长度阈值（tool 消息 content 超过此长度且达到年龄才降级；
    # 默认 8000：常规工具输出（grep/读文件片段/短日志）不触发折叠，大输出（长日志/抓取全文）才降级；
    # 折叠时提取关键事实摘要优先、首尾截断兜底；越小越省 token，越大越少折叠触发）
    tool_trim_threshold: int = 8000
    # ── EXEC_MODE 命令分级（EVO-20260810-2549e9b6）──
    # 默认空 = 不启用分级（AI 可执行 shell，仅灾难性硬阻断）；可选 readonly/allowlist/blocked 安全分级
    exec_mode: str = ""
    exec_allowlist: str = ""  # allowlist 模式的命令前缀白名单（逗号分隔）
    # ── EVO-20260814 P1-A: RUN_MODE 运行模式（对齐 Harness 四种运行模式）──
    # standard/ptc/minimal/creative（默认 standard 全工具集，零回归）
    run_mode: str = "standard"
    # ── EVO-d5db88d9: 工具 Schema 索引化（TOOL_SCHEMA_LAZY=1 时 LLM 只见精简索引，按需读完整 Schema）──
    # EVO-20260814: 默认开（节 token；环境变量仍可覆盖回 0 兼容旧用户）
    tool_schema_lazy: bool = True
    # ── EVO-20260813-9ced1f4c: 工具执行瀑布（pipeline.py，默认全关零回归）──
    tool_pipeline_enabled: bool = False  # 总开关（TOOL_PIPELINE_ENABLED）
    tool_materialize_enabled: bool = False  # 参数物化+深冻结（TOOL_MATERIALIZE_ENABLED）
    tool_guard_enabled: bool = False  # 单调守卫（TOOL_GUARD_ENABLED）

    # ── 上下文 ──
    history_max_chars: int = 100000  # T2(2026-08-14): 类默认收敛与运行时 env 默认一致（100K；1M 曾撑爆窗口，30000 过保守）
    memory_top_k: int = 5  # auto-adaptive: env 未显式设置时按上下文占用率自适应（>70%→8/<30%→3，硬上限 20）

    # ── 架构自省（AI-serving, design.md §2.1.4）──
    self_inspection_enabled: bool = True
    status_report_cooldown_s: float = 60.0

    # ── 压缩档案（T22 另存提取替代截断）──
    archive_enabled: bool = True
    experiences_dir: str = "./experiences"  # P1-2: 经验库目录（默认项目根 experiences/）
    skills_dir: str = "./skills"  # B3(2026-08-14): 插件化 Skill 目录（skills/<name>/SKILL.md；空/不存在=零行为）
    docs_dir: str = "./docs"  # P2-3: 文档检索目录（默认项目根 docs/）
    archive_max_entries: int = 0  # R7: 单会话最大档案条目数（0=不限）
    archive_ttl_days: int = 0     # R7: 条目存活天数（0=不限）
    archive_segment_bytes: int = 104857600  # T3b(2026-08-14): 档案单文件分片阈值（默认 100MB；0=不分片）
    audit_ttl_days: int = 30      # P1-3: 审计 JSONL 条目存活天数（0=不清理）
    memory_max_entries: int = 0   # P1-5: 记忆条目上限（0=不限；超限淘汰 decay_score 最低）

    # ── P1 摘要（FR-P1-MEM, §3.6）──
    summary_mode: str = "off"  # off/sync/async
    summary_timeout_s: float = 30.0
    summary_max_input_chars: int = 100000
    summary_model: str = ""  # R6: 独立摘要模型（provider/model 引用，空=用主模型）

    # ── P1 语义检索（FR-P1-RET, §3.6）──
    embedding_provider: str = "none"  # none/hash/api
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""  # 仅 env 读取，脱敏
    embedding_dim: int = 128
    retrieve_timeout_s: float = 1.0
    retrieve_semantic_top_k: int = 20  # auto-adaptive: env 未显式设置时按检索分数自适应（<0.3→10/>0.7→30，硬上限 50）

    # ── P1 独立提取（FR-P1-EXT, §3.6）──
    extract_enabled: bool = True
    extract_interval_msgs: int = 20
    extract_cooldown_s: float = 600.0
    extract_max_input_chars: int = 100000
    extract_timeout_s: float = 60.0
    # M66 思考链瘦身: 提交给 LLM 的历史中仅保留最近 N 轮 assistant 思考链
    # （0=全部保留；缩减上下文体积，最近轮 THK-04 回传不受影响）
    reasoning_tail: int = 2

    # ── P1 校验语义匹配（FR-P1-OPT-01, §3.6）──
    validate_semantic: bool = False
    validate_semantic_threshold: float = 0.75

    # ── M12 AI 自主闭环（§9，默认值保零回归）──

    selfheal_max_attempts: int = 3  # 单故障自愈尝试次数上限
    selfheal_max_per_round: int = 6  # 单轮自愈动作上限
    param_adjust_per_round: int = 3  # 单轮参数调整次数上限

    evolve_enabled: bool = True  # 演进建议通道
    # EVOLVE_LOCAL_EXEC: int（0=仅建议 / 1=白名单局部执行 / 2=全面执行）
    # 向后兼容: _env_evolve_level 读取 0/1/2；旧布尔 true/false 映射 1/0；非法回退 0
    evolve_local_exec: int = 0  # AI 局部演进执行权限（默认仅建议）
    evolve_exec_whitelist: str = (
        ""  # 执行白名单（逗号分隔影响范围/模块/动作类型；级别 1 时仅白名单内自动执行）
    )
    self_eval_enabled: bool = True  # 自我评估能力开关（0 时 self_evaluate 工具不注册 + 触发不提醒）
    self_eval_remind_enabled: bool = (
        True  # [自我评估提醒] 触发提示开关（0 仅支持 AI 主动 self_evaluate）
    )
    self_eval_interval_rounds: int = 50  # auto-adaptive: env 未显式设置时按异常率自适应（>20%→20/<5%→80，硬上限 200）
    self_eval_min_samples: int = 5  # 指标最小样本数（不足 → 如实标注"样本不足"）
    self_eval_span: int = 50  # 评估聚合窗口（近 N 轮/条）

    # ── M20 LLM 思考模式（THK-01, §11.5.1）──
    thinking_mode: bool = True  # LLM_THINKING_MODE（enabled/disabled，默认 enabled）
    reasoning_effort: str = "high"  # LLM_REASONING_EFFORT（low/high/max，默认 high）

    # ── M47 Provider 注册表原始 JSON（design §5.1）──
    # 仅承载 MODEL_PROVIDERS env 的原始字符串, 解析由 llm.providers.load_registry 完成 (fail-soft).
    # to_status_dict 不输出原始 JSON（不暴露配置细节, 仅暴露 bool 标志）.
    model_providers_raw: str = ""

    # ── M49 Fallback 链原始字符串（design §5.4）──
    # 仅承载 MODEL_FALLBACKS env 的原始字符串（逗号分隔 provider/model 引用）,
    # 解析由 llm.pool.ModelClientPool.fallback_candidates 完成（非法条目跳过, 空 = 不启用）.
    # to_status_dict 不输出明细（不暴露降级链细节）, 仅暴露计数（model_fallbacks_count）.
    # 降级仅在默认装配模型失败时生效；会话显式 override（含用户/AI 经 switch_model 选择）
    # 走严格模式失败直接如实反馈，不自动降级（design §5.4 行为规则表核心）。
    model_fallbacks_raw: str = ""

    # 运行时装配（非 env）: 由 builder 注入
    _extra: dict = field(default_factory=dict, repr=False, compare=False)

    # 配置项非法值回退标注（装配期注入，运行时只读；不含 raw 原文）
    invalid_fallbacks: tuple = field(default_factory=tuple, repr=False, compare=False)

    # T3 配置面收敛: env 未显式设置的可自适应配置项集合（消费方据此决定是否走自适应）
    auto_adaptive_keys: frozenset = field(default_factory=frozenset, repr=False, compare=False)

    # ── 派生路径 ──
    @property
    def sessions_dir(self) -> Path:
        return Path(self.data_dir) / "sessions"

    @property
    def event_logs_dir(self) -> Path:
        """事件日志目录（D1 单一真相源；EVENT_LOGS_DIR 覆盖，默认 data_dir/event_logs）."""
        if self.event_logs_dir_override:
            return Path(self.event_logs_dir_override)
        return Path(self.data_dir) / "event_logs"

    @property
    def memory_dir(self) -> Path:
        return Path(self.data_dir) / "memory"

    @property
    def audit_dir(self) -> Path:
        return Path(self.data_dir) / "audit"

    @property
    def archive_dir(self) -> Path:
        return Path(self.data_dir) / "archives"

    @property
    def recovery_dir(self) -> Path:
        return Path(self.data_dir) / ".recovery"

    def ensure_dirs(self) -> None:
        """确保运行时数据目录存在（幂等）."""
        dirs = [self.sessions_dir, self.memory_dir, self.audit_dir, self.recovery_dir]
        if self.archive_enabled:
            dirs.append(self.archive_dir)
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def to_status_dict(self) -> dict:
        """架构状态可呈现的配置摘要（不含密钥）."""
        return {
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            # M20（DFX-MNT-07）: 模型与思考参数（AI 可经 architecture_status 自查）
            "thinking_mode": self.thinking_mode,
            "reasoning_effort": self.reasoning_effort,
            "max_iterations": self.max_iterations,
            "llm_timeout_s": self.llm_timeout_s,
            "tool_timeout_s": self.tool_timeout_s,
            "tool_max_output_chars": self.tool_max_output_chars,
            "tool_summary_threshold": self.tool_summary_threshold,
            "tool_trim_enabled": self.tool_trim_enabled,
            "tool_schema_lazy": self.tool_schema_lazy,
            "tool_pipeline_enabled": self.tool_pipeline_enabled,
            "tool_materialize_enabled": self.tool_materialize_enabled,
            "tool_guard_enabled": self.tool_guard_enabled,
            "history_max_chars": self.history_max_chars,
            "memory_top_k": self.memory_top_k,
            "self_inspection_enabled": self.self_inspection_enabled,
            # P1 配置摘要（不含密钥）
            "summary_mode": self.summary_mode,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "extract_enabled": self.extract_enabled,
            "extract_interval_msgs": self.extract_interval_msgs,
            "validate_semantic": self.validate_semantic,
            # EVO-20260814 P1-A: RUN_MODE 运行模式（standard/ptc/minimal/creative，可查可验证）
            "run_mode": self.run_mode,
            # M12 深化（EXEC-01/08 + EVAL-02/03，architecture_config 可查）
            "evolve_local_exec": self.evolve_local_exec,
            "evolve_exec_whitelist": self.evolve_exec_whitelist,
            "self_eval_enabled": self.self_eval_enabled,
            "self_eval_remind_enabled": self.self_eval_remind_enabled,
            "self_eval_interval_rounds": self.self_eval_interval_rounds,
            "self_eval_min_samples": self.self_eval_min_samples,
            "self_eval_span": self.self_eval_span,
            # P2-3: 文档检索入口状态（AI 可自查，不暴露路径细节）
            "docs_search_enabled": bool(self.docs_dir),
            # M47: Provider 注册表配置状态（AI 可自查, 不暴露原始 JSON）
            "model_providers_configured": bool(self.model_providers_raw),
            # M49: Fallback 链配置状态（仅计数, 不暴露降级链明细, 密钥安全 DFX-SEC-02）
            "model_fallbacks_count": _count_fallbacks(self.model_fallbacks_raw),
            # 配置项非法值回退标注（如实标注，AI 可感知；不含密钥与 raw 原文）
            "config_invalid_fallbacks": [
                {
                    "config_name": n.config_name,
                    "fallback_value": n.fallback_value,
                    "invalid_value_type": n.invalid_value_type,
                }
                for n in self.invalid_fallbacks
            ],
            # T3: env 未显式设置的可自适应配置项（AI 可经 architecture_status 感知哪些参数在自适应）
            "auto_adaptive_keys": sorted(self.auto_adaptive_keys),
        }


def load_settings() -> Settings:
    """从环境变量装配 Settings；缺少必填项时抛出带指引的 ValueError."""
    _fallback_notes.clear()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    # M20 CFG-01/02: LLM_MODEL 缺省 → OPENSYGAI_DEEPSEEK_DEFAULT_MODEL → 内置 deepseek-v4-flash
    model = os.environ.get("LLM_MODEL", "").strip()
    if not model:
        model = (
            os.environ.get("OPENSYGAI_DEEPSEEK_DEFAULT_MODEL", "").strip() or "deepseek-v4-flash"
        )

    missing: list[str] = []
    if not api_key:
        missing.append("LLM_API_KEY")
    if not base_url:
        missing.append("LLM_BASE_URL")
    if missing:
        raise ValueError(
            "缺少必填环境变量: "
            + ", ".join(missing)
            + "。请参考 .env.example 配置 LLM_API_KEY / LLM_BASE_URL（LLM_MODEL 缺省默认 deepseek-v4-flash）。"
        )

    # T3: 记录 env 未显式设置的可自适应配置项（消费方据此走自适应，env 显式设置时走固定值）
    _auto_adaptive_keys: set[str] = set()
    if not os.environ.get("TOOL_TRIM_AGE", "").strip():
        _auto_adaptive_keys.add("tool_trim_age")
    if not os.environ.get("MEMORY_TOP_K", "").strip():
        _auto_adaptive_keys.add("memory_top_k")
    if not os.environ.get("RETRIEVE_SEMANTIC_TOP_K", "").strip():
        _auto_adaptive_keys.add("retrieve_semantic_top_k")
    if not os.environ.get("SELF_EVAL_INTERVAL_ROUNDS", "").strip():
        _auto_adaptive_keys.add("self_eval_interval_rounds")

    return Settings(
        llm_api_key=api_key,
        llm_base_url=base_url,
        llm_model=model,
        thinking_mode=_env_thinking_mode("LLM_THINKING_MODE"),
        reasoning_effort=_env_effort("LLM_REASONING_EFFORT"),
        max_iterations=_env_int("LLM_MAX_ITERATIONS", 40),
        llm_timeout_s=float(_env_int("LLM_TIMEOUT_S", 120)),
        data_dir=os.environ.get("DATA_DIR", "./data").strip(),
        # D1 事件日志（EVENT_LOG_ENABLED / EVENT_LOGS_DIR 透传）
        event_log_enabled=_env_bool("EVENT_LOG_ENABLED", True),
        event_logs_dir_override=os.environ.get("EVENT_LOGS_DIR", "").strip(),
        read_path_source=os.environ.get("READ_PATH_SOURCE", "session_json").strip(),
        event_log_rotate_bytes=int(os.environ.get("EVENT_LOG_ROTATE_BYTES", str(10 * 1024 * 1024))),
        event_log_rotate_days=int(os.environ.get("EVENT_LOG_ROTATE_DAYS", "30")),
        event_log_rotate_on_session_end=_env_bool("EVENT_LOG_ROTATE_ON_SESSION_END", True),
        event_hooks_config=os.environ.get("EVENT_HOOKS_CONFIG", "").strip(),
        tool_timeout_s=float(_env_int("TOOL_TIMEOUT_S", 60)),
        tool_max_output_chars=_env_int("TOOL_MAX_OUTPUT_CHARS", 100000),
        tool_summary_threshold=_env_int("TOOL_SUMMARY_THRESHOLD", 12000),  # 2026-08-15 放大字数
        tool_trim_enabled=_env_bool("TOOL_TRIM_ENABLED", True),
        tool_trim_age=_env_int("TOOL_TRIM_AGE", 0),
        tool_trim_threshold=_env_int("TOOL_TRIM_THRESHOLD", 8000),
        exec_mode=_env_exec_mode("EXEC_MODE"),
        exec_allowlist=os.environ.get("EXEC_ALLOWLIST", "").strip(),
        run_mode=_env_run_mode("RUN_MODE"),
        tool_schema_lazy=_env_bool("TOOL_SCHEMA_LAZY", True),  # EVO-20260814: 默认开
        tool_pipeline_enabled=_env_bool("TOOL_PIPELINE_ENABLED", False),
        tool_materialize_enabled=_env_bool("TOOL_MATERIALIZE_ENABLED", False),
        tool_guard_enabled=_env_bool("TOOL_GUARD_ENABLED", False),
        history_max_chars=_env_int("HISTORY_MAX_CHARS", 100000),  # T2(2026-08-14): 默认 100K（与类默认收敛；1M 曾致上下文撑爆全失败）
        memory_top_k=_env_int("MEMORY_TOP_K", 5),
        self_inspection_enabled=_env_bool("SELF_INSPECTION_ENABLED", True),
        status_report_cooldown_s=float(_env_int("STATUS_REPORT_COOLDOWN_S", 60)),
        archive_enabled=_env_bool("ARCHIVE_ENABLED", True),
        experiences_dir=os.environ.get("EXPERIENCES_DIR", "./experiences").strip(),
        skills_dir=os.environ.get("SKILLS_DIR", "./skills").strip(),  # B3: 插件化 Skill 目录
        docs_dir=os.environ.get("DOCS_DIR", "./docs").strip(),
        archive_max_entries=_env_int("ARCHIVE_MAX_ENTRIES", 0),
        archive_ttl_days=_env_int("ARCHIVE_TTL_DAYS", 0),
        archive_segment_bytes=_env_int("ARCHIVE_SEGMENT_BYTES", 104857600),  # T3b: 默认 100MB（0=不分片）
        audit_ttl_days=_env_int("AUDIT_TTL_DAYS", 30),
        memory_max_entries=_env_int("MEMORY_MAX_ENTRIES", 0),
        # P1（design.md §3.6，非法值回退默认）
        summary_mode=os.environ.get("SUMMARY_MODE", "off").strip().lower() or "off",
        summary_timeout_s=float(_env_int("SUMMARY_TIMEOUT_S", 30)),
        summary_max_input_chars=_env_int("SUMMARY_MAX_INPUT_CHARS", 100000),
        summary_model=os.environ.get("SUMMARY_MODEL", "").strip(),
        embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "none").strip().lower() or "none",
        embedding_base_url=os.environ.get("EMBEDDING_BASE_URL", "").strip(),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "").strip(),
        embedding_api_key=os.environ.get("EMBEDDING_API_KEY", "").strip(),
        embedding_dim=_env_int("EMBEDDING_DIM", 128),
        retrieve_timeout_s=float(_env_int("RETRIEVE_TIMEOUT_S", 1)),
        retrieve_semantic_top_k=_env_int("RETRIEVE_SEMANTIC_TOP_K", 20),
        extract_enabled=_env_bool("EXTRACT_ENABLED", True),
        extract_interval_msgs=_env_int("EXTRACT_INTERVAL_MSGS", 20),
        reasoning_tail=_env_int("REASONING_TAIL", 2),  # M66 思考链瘦身（0=全部保留）
        extract_cooldown_s=float(_env_int("EXTRACT_COOLDOWN_S", 600)),
        extract_max_input_chars=_env_int("EXTRACT_MAX_INPUT_CHARS", 100000),
        extract_timeout_s=float(_env_int("EXTRACT_TIMEOUT_S", 60)),
        validate_semantic=_env_bool("VALIDATE_SEMANTIC", False),
        validate_semantic_threshold=float(_env_int("VALIDATE_SEMANTIC_THRESHOLD", 0)) or 0.75,
        # M12 AI 自主闭环（§9，默认值保零回归）
        selfheal_max_attempts=_env_int("SELFHEAL_MAX_ATTEMPTS", 3),
        selfheal_max_per_round=_env_int("SELFHEAL_MAX_PER_ROUND", 6),
        param_adjust_per_round=_env_int("PARAM_ADJUST_PER_ROUND", 3),
        evolve_enabled=_env_bool("EVOLVE_ENABLED", True),
        evolve_local_exec=_env_evolve_level("EVOLVE_LOCAL_EXEC"),
        evolve_exec_whitelist=os.environ.get("EVOLVE_EXEC_WHITELIST", "").strip(),
        self_eval_enabled=_env_bool("SELF_EVAL_ENABLED", True),
        self_eval_remind_enabled=_env_bool("SELF_EVAL_REMIND_ENABLED", True),
        self_eval_interval_rounds=_env_int("SELF_EVAL_INTERVAL_ROUNDS", 50),
        self_eval_min_samples=_env_int("SELF_EVAL_MIN_SAMPLES", 5),
        self_eval_span=_env_int("SELF_EVAL_SPAN", 50),
        # M47（design §5.1）: MODEL_PROVIDERS 注册表 JSON, 解析由 llm.providers.load_registry 完成
        model_providers_raw=os.environ.get("MODEL_PROVIDERS", "").strip(),
        # M49（design §5.4）: MODEL_FALLBACKS 降级链原始值, 解析由 llm.pool 完成
        model_fallbacks_raw=os.environ.get("MODEL_FALLBACKS", "").strip(),
        invalid_fallbacks=tuple(_fallback_notes),
        auto_adaptive_keys=frozenset(_auto_adaptive_keys),
    )
