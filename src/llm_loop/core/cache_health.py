"""EVO-20260817-72fcd94a: 缓存健康闭环（独立模块，控制 engine.py 体量）.

程序常态锚点管理（用户 2026-08-17 决策）:
- 发送前门禁: preflight 发现前缀/锚点漂移 → 强制缓存友好压缩（保留锚点头部）→ 合规化;
  postcheck 确认本次发送前缀与基线一致 → 出闸（不合规只审计 + 提示，fail-open 不阻断 run）。
- 窗口监控（归因判定，2026-08-17 DSH 043 修订）:
  破坏型（窗口内锚点前移 > 0）: 低命中 <50% → 告警注入 + 拦截（保留头部可救回前缀）。
  设计型（窗口内锚点前移 = 0）: 低命中为设计值（小窗口 100000 物理决定），只观察不告警。
  恢复: 拦截期锚点未再前移连续 min_runs 轮 → 解除（不再依赖命中率回升——设计 8% 永远
  达不到 80%，原条件死锁）；超时兜底 recovery_timeout_runs 轮未恢复 → 恢复失败短消息 +
  解除（每进程一次，防刷屏）。监控目标 = 验证前缀稳定机制在工作（锚点/注入无异常），
  而非命中率高（命中率降为观察指标；成本维度另由 usage_cost_report 覆盖）。
所有方法 fail-open，异常不影响主循环。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ── P0 压缩风暴熔断（2026-08-25 规格）──
# 触发: 连续 (context.compressed 且 压缩后上下文仍超压缩线) 轮数达阈值 且
#   窗口命中率低于 BREAKER_HIT_THR → 进入 breaker。
#   ⚠️ 锚点移动不是必要条件（2026-08-25 真实冒烟修正）: head_keep 模式下锚点冻结
#   但保留窗口每轮前移（新消息顶替旧保留组）→ 前缀在窗口边界持续断 → 命中钉死
#   低值——同样是风暴，只是没有 anchor 前移。区分折叠与风暴靠命中共信号:
#   折叠轮每轮只折最老 K 组、字节变化极小、命中率高 → 不触发；风暴轮命中钉死
#   → 触发。（规格要求以结构计数为核心，命中率是共信号不是唯一信号。）
# 冻结: 禁止程序兜底压缩 + 锚点不前移（build 侧配合 freeze_compression）。
# 压力: 冻结期上下文超安全水位（预算×BREAKER_PRESSURE_RATIO，与 cache_guard 规则 F
#   BLOCK 阈值 0.95 对齐——breaker 前置拦截，规则 F 永不双拦）→ context_pressure
#   （不提交；AI 先 checkpoint/换会话）。
# 退出: 明确 hysteresis——cooldown 轮数下限 + 上下文低于退出水位 + 无压缩连续稳定。
# 逃生: 连续 context_pressure 达 BREAKER_PRESSURE_ESCAPE_MAX → 允许一次受控压缩
#   （防永久死锁；单次压缩后仍超限 → 再次压力循环，烧损有界）。
# 审计: data/audit/cache_breaker.jsonl（storm_count/anchor/enter/exit/pressure/escape）。
_BREAKER_TRIGGER_RUNS = int(os.environ.get("BREAKER_TRIGGER_RUNS", "5"))
_BREAKER_COOLDOWN_ROUNDS = int(os.environ.get("BREAKER_COOLDOWN_ROUNDS", "8"))
_BREAKER_EXIT_STABLE_RUNS = int(os.environ.get("BREAKER_EXIT_STABLE_RUNS", "3"))
_BREAKER_EXIT_CHARS_RATIO = float(os.environ.get("BREAKER_EXIT_CHARS_RATIO", "0.8"))
_BREAKER_PRESSURE_RATIO = float(os.environ.get("BREAKER_PRESSURE_RATIO", "0.95"))
_BREAKER_PRESSURE_ESCAPE_MAX = int(os.environ.get("BREAKER_PRESSURE_ESCAPE_MAX", "6"))
_BREAKER_HIT_THR = float(os.environ.get("BREAKER_HIT_THR", "0.5"))  # 命中共信号（防折叠误判）
_BREAKER_OVER_RATIO = float(os.environ.get("BREAKER_OVER_RATIO", "0.9"))  # 压缩线（=compact_ratio 默认）


def _breaker_audit_path() -> Path:
    try:
        return Path(os.environ["LFL_DATA_DIR"]) / "audit" / "cache_breaker.jsonl"
    except Exception:  # noqa: BLE001
        return Path(__file__).resolve().parents[3] / "data" / "audit" / "cache_breaker.jsonl"


# ── P1 遥测内容/传输分层（2026-08-25 规格）──
# 程序遥测（⚡ 缓存命中率 ...）不再写入 assistant.content：正文只存纯回答，
# 遥测进 metadata.cache_health，transport 层渲染。此正则用于剥离:
#   ① legacy 历史（旧会话已把遥测写进正文）→ build 时从提交视图剥离;
#   ② 模型本轮自行生成的同格式伪造行 → 落库/返回前剥离。
_TELEMETRY_LINE_RE = re.compile(r"(?m)^[ \t]*⚡ 缓存命中率 [^\n]*?tokens）[ \t]*\n")
_TELEMETRY_LINE_EOF_RE = re.compile(r"(?m)^[ \t]*⚡ 缓存命中率 [^\n]*?tokens）[ \t]*$")
# 任务4（2026-08-25 §5.10）: 末尾位置限定——遥测总是程序注入在回答末尾（legacy）
# 或模型伪造在末尾；正文中部出现"缓存命中率"字样属正常论述，不应误剥离。
# 默认仅检查末尾 N 行（=0 时回退全文匹配兼容旧行为）。
_STRIP_AUDIT_LOG = os.environ.get("CACHE_TELEMETRY_STRIP_AUDIT_LOG", "0") == "1"
_STRIP_TAIL_LINES = int(os.environ.get("CACHE_TELEMETRY_STRIP_TAIL_LINES", "10"))


def strip_cache_telemetry_lines(content: str | None, *, audit_log: bool = False) -> str:
    """剥离 `⚡ 缓存命中率 ... tokens）` 行（legacy + 模型伪造），保持其余字节不变.

    任务4（§5.10）: 末尾位置限定——仅末尾 _STRIP_TAIL_LINES 行（默认 10）参与剥离
    （总行数 ≤ N 时全文检查；=0 时回退全文匹配）。剥离量异常大（ratio<0.8）→
    WARN「遥测剥离疑似误伤」；audit_log=True 或 CACHE_TELEMETRY_STRIP_AUDIT_LOG=1
    时输出 debug 级审计日志。
    """
    if not content or "缓存命中率" not in content:
        return content or ""
    lines: list[str | None] = list(content.splitlines(keepends=True))
    n = len(lines)
    limit = _STRIP_TAIL_LINES
    start = 0 if limit <= 0 or n <= limit else n - limit
    removed = 0
    for i in range(start, n):
        line = lines[i]
        if line is not None and (
            _TELEMETRY_LINE_RE.match(line) or _TELEMETRY_LINE_EOF_RE.match(line)
        ):
            lines[i] = None
            removed += 1
    if not removed:
        return content
    stripped = "".join(ln for ln in lines if ln is not None)
    # 行剥离后归一化连续空行（防正文尾部/行间留空洞）
    if stripped != content:
        stripped = re.sub(r"\n{3,}", "\n\n", stripped).rstrip()
    # 误伤检测: 剥离比例异常 → WARN（正文大量命中"缓存命中率"论述被误删）
    try:
        before = len(content)
        after = len(stripped)
        if before > 0 and after / before < 0.8:
            logger.warning(
                "遥测剥离疑似误伤: before=%d after=%d ratio=%.2f（尾部%d行参与检查）",
                before, after, after / before, n - start,
            )
        if audit_log or _STRIP_AUDIT_LOG:
            logger.debug(
                "遥测剥离审计: removed=%d lines tail=%d before=%d after=%d",
                removed, n - start, before, after,
            )
    except Exception:  # noqa: BLE001 — fail-open
        logger.debug("遥测剥离审计异常（fail-open）", exc_info=True)
    return stripped


@dataclass
class _BreakerState:
    """单会话压缩风暴熔断状态（按 session 隔离——健康会话不受风暴会话牵连）."""

    storm_streak: int = 0  # 连续 (compacted 且 anchor_moved) 轮数
    active: bool = False
    rounds: int = 0  # 进入后经过的 build 轮数（cooldown 下限）
    clean_runs: int = 0  # 连续（无压缩 且 anchor 未动 且 低于退出水位）轮数
    pressure_runs: int = 0  # 连续 context_pressure 轮数
    pressure_escape: bool = False  # 逃生已武装：允许一次受控压缩
    entered_at: float = 0.0
    enter_reason: str = ""
    exit_reason: str = ""
    last_chars: int = 0
    last_budget: int = 0


@dataclass
class _SessionBucket:
    """EVO-20260825: per-session 窗口状态（并发串台隔离——各会话命中统计独立）."""

    win_in: int = 0
    win_hit: int = 0
    win_runs: int = 0
    last_update_ts: float = 0.0
    alerted: bool = False
    good_streak: int = 0
    anchor_moved_in_win: int = 0
    anchor_moved_since_record: bool = False
    force_head_keep: bool = False
    gate_note_pending: bool = False
    # EVO-20260827-ad73251b: 命中趋势转折点观测（滚动 30 轮，纯内存 fail-open）。
    # 判定语义: first_recovery_round 存在且 current_streak 高 → 冷启动暂时态；
    # anchor_moved>0 且 streak 低 → 破坏型（持续断点）。模型切换重建桶时自然重置。
    trend: deque = field(default_factory=lambda: deque(maxlen=30))
    trend_rounds: int = 0

# Legacy wire compatibility text for pre-R8.11 gate-note history/recovery fixtures.
# R8.11 no longer emits this text into live provider prompts; cache-gate state is
# runtime observability and is exposed through monitor/action status instead.
GATE_NOTE_CONTENT = (
    "[门禁干预] 缓存门禁检测到前缀漂移/低命中，本轮起强制保留历史头部"
    "（锚点未前移，历史更完整属预期）；你无需处理，正常消费即可。"
)


class CacheHealthMonitor:
    """缓存健康监控 + 发送前门禁（单实例挂 engine）."""

    def __init__(
        self,
        *,
        min_runs: int = 5,
        min_tokens: int = 50000,
        alert_thr: float = 0.5,
        recover_thr: float = 0.8,
        force_head_ratio: float = 0.15,
        recovery_timeout_runs: int = 20,
        # P0 压缩风暴熔断参数（env 可调，见模块常量）
        breaker_trigger_runs: int = _BREAKER_TRIGGER_RUNS,
        breaker_cooldown_rounds: int = _BREAKER_COOLDOWN_ROUNDS,
        breaker_exit_stable_runs: int = _BREAKER_EXIT_STABLE_RUNS,
        breaker_exit_chars_ratio: float = _BREAKER_EXIT_CHARS_RATIO,
        breaker_pressure_ratio: float = _BREAKER_PRESSURE_RATIO,
        breaker_pressure_escape_max: int = _BREAKER_PRESSURE_ESCAPE_MAX,
        breaker_hit_thr: float = _BREAKER_HIT_THR,
        breaker_over_ratio: float = _BREAKER_OVER_RATIO,
        breaker_audit_file: str | Path | None = None,
    ) -> None:
        # EVO-20260825: per-session 分桶（并发串台隔离）——各会话命中窗口独立
        self._session_buckets: dict[str, _SessionBucket] = {}
        # 归因（进程级累计计数——审计用，非窗口判定）
        self._anchor_move_runs = 0
        # 2026-08-20: 上次 record 的模型 ref（跨模型交替时缓存按 provider 独立预热）
        self._last_model_ref: str | None = None
        # 2026-08-20 (EVO-20260820-0b96348d 镜像检验): 按模型分桶累计（跨切换持久）——
        # 活动窗口（_session_buckets 内）仍按"切换即重置"语义，桶数据附加保留，
        # 供双口径展示与"切回热检查"（hit>0 说明旧桶缓存仍热，可继续累加不误清零）。
        # 桶结构: {model_ref: {"in": int, "hit": int, "runs": int}}
        self._buckets: dict[str, dict[str, int]] = {}
        # 发送前门禁（per-session 基线: 不同会话注入/记忆不同，互不干扰）
        # 双轴基线（ARCHITECTURE-cache-prefix-surface-contract-v1 §3/§5.3）:
        # - system 轴: 裸 system+稳定注入段指纹 → 基线不符 = 真漂移（干预+计数）；
        # - tools 轴: 仅记上一轮指纹做合法变更审计计数（schema/顺序变化不干预不计 drift）。
        self._system_baselines: dict[str, str] = {}  # session_id → system 轴指纹
        self._tools_prev_fp: dict[str, str] = {}  # session_id → 上一轮 tools 轴指纹
        self._tools_change_count = 0  # tools 轴合法变更计数（logger+计数器，不进 snapshot；§10 Q2 已决）
        self._gate_drift_count = 0
        # 参数
        self._min_runs = min_runs
        self._min_tokens = min_tokens
        self._alert_thr = alert_thr
        self._recover_thr = recover_thr
        self._force_head_ratio = force_head_ratio
        self._recovery_timeout_runs = recovery_timeout_runs
        # P0 压缩风暴熔断（per-session 状态——健康会话不受风暴会话牵连）
        self._breaker_trigger_runs = breaker_trigger_runs
        self._breaker_cooldown_rounds = breaker_cooldown_rounds
        self._breaker_exit_stable_runs = breaker_exit_stable_runs
        self._breaker_exit_chars_ratio = breaker_exit_chars_ratio
        self._breaker_pressure_ratio = breaker_pressure_ratio
        self._breaker_pressure_escape_max = breaker_pressure_escape_max
        self._breaker_hit_thr = breaker_hit_thr
        self._breaker_over_ratio = breaker_over_ratio
        self._breaker_audit_file = (
            Path(breaker_audit_file) if breaker_audit_file else _breaker_audit_path()
        )
        self._breakers: dict[str, _BreakerState] = {}
        # 命中共信号独立滚动窗口（per-session——并发串台隔离；风暴期窗口常被
        # 重置而样本不足，独立窗口保证共信号始终有据可依）
        self._breaker_hit_win: dict[str, list[tuple[int, int]]] = {}
        # EVO-20260825 §5.11: 恢复失败 per-session 防刷屏（每会话仅首次提示）
        self._fail_alerted_sessions: set[str] = set()

    def _get_bucket(self, session_id: str = "") -> _SessionBucket:
        """获取或创建 per-session 窗口桶（默认 __default__ 兼容无 session_id 调用方）."""
        sid = session_id or "__default__"
        b = self._session_buckets.get(sid)
        if b is None:
            b = _SessionBucket()
            # 门禁路径（preflight 漂移）不经 record_usage 就建桶；不盖章则 ts=0，
            # 聚合 snapshot 的惰性清理会把刚建的门禁桶当超时死桶清除（A4 红灯根因）。
            # 仅创建时盖章：record_usage 每次刷新，snapshot 轮询不续命（否则永不清理）。
            b.last_update_ts = time.time()
            self._session_buckets[sid] = b
        return b

    @staticmethod
    def _trend_append(b: _SessionBucket, tokens_in: int, tokens_hit: int) -> None:
        """趋势采样（fail-open 由调用方 try 包裹；环形缓冲 maxlen 自动淘汰旧样本）."""
        b.trend_rounds += 1
        b.trend.append({"round": b.trend_rounds, "tokens_in": tokens_in, "hit": tokens_hit})

    @staticmethod
    def _trend_summary(b: _SessionBucket) -> dict:
        """派生转折点指标: first_recovery_round（首个 hit>0 轮）+ current_streak."""
        first_recovery = next(
            (s["round"] for s in b.trend if s["hit"] > 0), None
        )
        streak = 0
        for s in reversed(b.trend):
            if s["hit"] > 0:
                streak += 1
            else:
                break
        return {
            "first_recovery_round": first_recovery,
            "current_streak": streak,
            "samples": len(b.trend),
            "total_rounds": b.trend_rounds,
            "recent": list(b.trend)[-10:],
        }

    # ── 窗口监控（run 末尾调用）──
    def record(self, tokens_in: int, tokens_hit: int, model_ref: str | None = None,
               session_id: str = "") -> str | None:
        """累计窗口并做告警/恢复判定，返回注入提示或 None（fail-open）.

        2026-08-20（镜像，观测正确性）: model_ref 感知——模型切换（如跨端 web=minimax /
        飞书=deepseek 交替，或 fallback 切模型）时**缓存按 provider 独立预热**，切换后
        低命中是设计型（新模型无前缀），**不是锚点漂移**。此时重置窗口并返回归因提示，
        不触发"锚点前移破坏"告警/拦截（避免误报误导）。

        归因判定（2026-08-17 DSH 043）:
        - 破坏型（窗口内锚点前移 > 0）: 低命中 → 告警 + 拦截（保留头部可救回前缀）。
        - 设计型（窗口内锚点前移 = 0）: 低命中为设计值（小窗口物理决定），只观察不拦截。
        - 模型切换（2026-08-20）: 设计型子类——新模型前缀从零预热，重置窗口+归因提示。
        恢复（不再依赖命中率回升——设计 8% 达不到 80%，原条件死锁）:
        - 拦截期锚点未再前移连续 min_runs 轮 → 解除。
        - 超时兜底: 拦截期累计 recovery_timeout_runs 轮未恢复 → 恢复失败短消息 + 解除
          （每会话一次，防刷屏）。

        EVO-20260825: session_id 分桶——各会话命中窗口独立，并发串台不污染。
        """
        try:
            sid = session_id or "__default__"
            b = self._get_bucket(sid)
            b.last_update_ts = time.time()
            # P0: 命中共信号滚动窗口（近 8 次，per-session 独立，fail-open）
            win = self._breaker_hit_win.setdefault(sid, [])
            win.append((tokens_in, tokens_hit))
            del win[:-8]
            # EVO-20260827-ad73251b: 趋势转折点采样（切换轮在重建桶后单独补记，此处
            # 切换轮写入旧桶会被丢弃，无双计）
            self._trend_append(b, tokens_in, tokens_hit)
            # 2026-08-20: 模型切换检测——切换后缓存按新 provider 独立预热（设计型低命中）
            switched = model_ref is not None and self._last_model_ref not in (None, model_ref)
            # 2026-08-20 (EVO-20260820-0b96348d): 每轮累计进当前模型桶（跨切换持久）
            if model_ref is not None:
                self._accum_bucket(model_ref, tokens_in, tokens_hit)
            _prev_model = self._last_model_ref  # 切换前的旧模型（覆盖前取值）
            if model_ref is not None:
                self._last_model_ref = model_ref
            if switched:
                # 2026-08-20: 模型切换 → 重置窗口并**累加切换轮**（新模型第一轮计入
                # 新窗口）→ 返回归因提示, 不进入锚点漂移告警判定
                _from = _prev_model
                self._session_buckets[sid] = b = _SessionBucket()
                b.win_in += tokens_in
                b.win_hit += tokens_hit
                b.win_runs += 1
                b.last_update_ts = time.time()
                self._trend_append(b, tokens_in, tokens_hit)  # 切换轮计入新桶趋势
                # 2026-08-20 (EVO-20260820-0b96348d): 切回热检查——切回的目标模型若
                # 已有历史桶且命中（前缀曾热，TTL 内），提示可继续累加而非从头预热；
                # 无历史/冷桶 → 常规提示（新模型无前缀）。
                # 注意: 本轮已把切回轮累计进目标桶，须用**累计前**的历史值判断
                # （排除本轮刚累加的高命中，避免"切回首轮正常命中"被误判为历史热）。
                _target_bucket = self._buckets.get(model_ref) if model_ref else None
                _hist_runs = max(0, (_target_bucket or {}).get("runs", 0) - 1)
                _hist_hit = max(0, (_target_bucket or {}).get("hit", 0) - tokens_hit)
                _hist_in = max(0, (_target_bucket or {}).get("in", 0) - tokens_in)
                if _hist_runs > 0 and _hist_hit > 0:
                    return (
                        f"[模型切换 {_from}→{model_ref}] 缓存按模型独立预热；"
                        f"目标模型历史桶命中 {_hist_hit:,}/{_hist_in:,}"
                        " tokens 仍热（TTL 内），切回可继续累加不误清零；非前缀漂移，无需干预。"
                    )
                return (
                    f"[模型切换 {_from}→{model_ref}] 缓存按模型独立预热（新模型无前缀），"
                    "命中率将从新模型重新统计；非前缀漂移，无需干预。"
                )
            b.win_in += tokens_in
            b.win_hit += tokens_hit
            b.win_runs += 1
            rate = b.win_hit / b.win_in if b.win_in else 1.0
            # 兼容旧代码: force_head_keep 进程级（干预激活 >=1 条即可）
            force_hk = any(bk.force_head_keep for bk in self._session_buckets.values())
            if b.alerted or force_hk:
                # 拦截期: 本轮锚点未前移 → 前缀已稳定，连续计数；本轮前移 → 重置
                moved_this_round = b.anchor_moved_since_record
                b.anchor_moved_since_record = False
                b.good_streak = (
                    b.good_streak + 1 if not moved_this_round else 0
                )
                if b.good_streak >= self._min_runs:
                    _runs, _hit, _in = b.win_runs, b.win_hit, b.win_in
                    b.alerted = False
                    b.force_head_keep = False
                    self._anchor_move_runs = 0
                    self._session_buckets[sid] = b = _SessionBucket()
                    b.last_update_ts = time.time()
                    return (
                        f"[缓存已恢复] 拦截期锚点未再前移（连续 {self._min_runs} 轮），"
                        f"前缀已稳定（近 {_runs} 次 run {_hit}/{_in} tokens），解除强制"
                        "缓存友好压缩，恢复正常监控。"
                    )
                if (
                    b.win_runs >= self._recovery_timeout_runs
                    and sid not in self._fail_alerted_sessions
                ):
                    self._fail_alerted_sessions.add(sid)
                    b.alerted = False
                    b.force_head_keep = False
                    self._anchor_move_runs = 0
                    self._session_buckets[sid] = b = _SessionBucket()
                    b.last_update_ts = time.time()
                    return (
                        f"[缓存恢复失败] 拦截 {self._recovery_timeout_runs} 轮命中率未回升"
                        f"（当前 {rate*100:.0f}%）。请查 architecture_status 定位原因"
                        "（预算/锚点/注入）；设计行为可确认接受（本会话仅提示一次）。"
                    )
                return None
            if (
                b.win_runs >= self._min_runs
                and b.win_in >= self._min_tokens
                and rate < self._alert_thr
            ):
                if b.anchor_moved_in_win == 0 or sid in self._fail_alerted_sessions:
                    # 设计型（锚点未前移，低命中为设计值）或已提示过恢复失败 →
                    # 只观察不告警不拦截（防噪音/刷屏）
                    return None
                cause = "近窗口内压缩锚点前移破坏前缀"
                # 告警文案快照（reset 前）——EVO-20260817-5b991577 缺陷1:
                # 原实现先 _reset_window() 再组装文案 → 显示"近 0 次 run 0/0 tokens"失真
                _runs, _hit, _in = b.win_runs, b.win_hit, b.win_in
                b.alerted = True
                b.force_head_keep = True
                b.gate_note_pending = True  # 干预激活 → 一次性观测标记待消费（R8.11 不进 prompt）
                # 拦截开始: 只重置窗口累计数据，保留 alerted/force_head_keep/gate_note_pending
                b.win_in = b.win_hit = b.win_runs = 0
                b.anchor_moved_in_win = 0
                b.anchor_moved_since_record = False
                return (
                    f"[缓存命中告警] 近 {_runs} 次 run 命中率 {rate*100:.0f}%"
                    f"（{_hit}/{_in} tokens）。{cause}。"
                    "已拦截：后续压缩强制缓存友好（保留锚点头部，前缀稳定）；"
                    "锚点不再前移后自动解除（不依赖命中率回升）。"
                    "成本放大 ~50 倍（hit 0.05/M vs miss 1.5/M）。"
                )
            return None
        except Exception:  # noqa: BLE001 — fail-open
            logger.warning("缓存窗口监控异常（fail-open）", exc_info=True)
            return None

    # ── 窗口监控（run 末尾调用）── 结束

    def _accum_bucket(self, model_ref: str, tokens_in: int, tokens_hit: int) -> None:
        """累计当前模型桶（跨切换持久；EVO-20260820-0b96348d 镜像检验）."""
        try:
            b = self._buckets.setdefault(model_ref, {"in": 0, "hit": 0, "runs": 0})
            b["in"] += tokens_in
            b["hit"] += tokens_hit
            b["runs"] += 1
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("模型桶累计异常（fail-open）", exc_info=True)

    def format_health_note(self, session_id: str = "") -> str | None:
        """EVO-20260819-2254e3b4 延伸（用户批准方案B）: 常态缓存命中率摘要（回答末尾展示）.

        与告警路径（record 返回）互不干扰：仅当窗口有数据且当前未处于拦截/告警期时
        返回一行精简命中率（近 N 轮窗口），供 engine 注入 final_answer 末尾。
        2026-08-20 (EVO-20260820-0b96348d 镜像检验): 双口径展示——本模型累计（桶，
        跨切换持久）+ 近 N 轮（活动窗口，近期热状态）。口径明确标注，避免跨模型累计稀释误导。
        EVO-20260825: session_id 分桶——读取对应会话窗口数据。
        fail-open: 任何异常返回 None，不阻断 run。
        """
        try:
            b = self._get_bucket(session_id)
            if b.win_runs <= 0 or b.alerted:
                return None
            rate = b.win_hit / b.win_in if b.win_in else 1.0
            parts = [
                f"⚡ 缓存命中率 {rate*100:.1f}%",
                f"（近 {b.win_runs} 轮，{b.win_hit:,}/{b.win_in:,} tokens",
            ]
            # 本模型累计口径（桶持久数据；模型切换不清零，只随真实累计增长）
            cur = self._buckets.get(self._last_model_ref or "")
            if cur and cur.get("runs", 0) > 0:
                total = cur["hit"] / cur["in"] if cur.get("in") else None
                if total is not None:
                    _model_name = (self._last_model_ref or "").split("/")[-1] or "本模型"
                    parts.append(
                        f"；本模型({_model_name})累计 {cur['runs']} 轮 {total*100:.1f}%"
                        f" {cur['hit']:,}/{cur['in']:,} tokens"
                    )
            parts.append("）")
            return "".join(parts)
        except Exception:  # noqa: BLE001 — fail-open
            logger.warning("缓存命中率摘要格式化异常（fail-open）", exc_info=True)
            return None


    def note_anchor_moved(self, session_id: str = "") -> None:
        """build 时锚点实际前移 → 记入归因（压缩破坏前缀证据）.
        EVO-20260825: session_id 分桶——归因窗口记入对应会话."""
        try:
            self._anchor_move_runs += 1
            b = self._get_bucket(session_id)
            b.anchor_moved_in_win += 1
            b.anchor_moved_since_record = True
        except Exception:  # noqa: BLE001
            logger.debug("anchor_move 计数异常（fail-open）", exc_info=True)

    # ── P0 压缩风暴熔断（2026-08-25 规格）──
    def _breaker(self, session_id: str) -> _BreakerState:
        st = self._breakers.get(session_id)
        if st is None:
            st = _BreakerState()
            self._breakers[session_id] = st
        return st

    def note_build_result(
        self,
        *,
        compacted: bool,
        anchor_moved: bool,
        chars_total: int,
        budget: int,
        session_id: str = "",
        model_ref: str = "",
    ) -> None:
        """build 后调用（每轮一次）: 风暴计数 + breaker 生命周期（fail-open）.

        风暴判定 = 连续 (compacted 且 压缩后仍超压缩线) 轮——每轮归档改写历史 +
        上下文压不回 → provider 前缀持续断（head_keep 模式下锚点冻结但保留窗口
        每轮前移，同样风暴——anchor_moved 不作必要条件，2026-08-25 冒烟修正）。
        干净轮（无压缩）清零。命中共信号（窗口命中率低于 BREAKER_HIT_THR）防
        渐进折叠误判（折叠轮命中率高）。达阈值 → 进入 breaker；breaker 内按
        退出 hysteresis 判定。
        """
        try:
            if not session_id:
                return
            st = self._breaker(session_id)
            st.last_chars = chars_total
            st.last_budget = budget
            if st.pressure_escape:
                # 逃生轮已消费（本轮允许一次受控压缩），下一轮恢复冻结
                st.pressure_escape = False
            if st.active:
                self._breaker_round_tick(st, compacted, anchor_moved, chars_total, budget,
                                         session_id, model_ref)
                return
            # 非 breaker 期: 风暴计数（结构信号：压缩 + 仍超压缩线）
            over = budget > 0 and chars_total > budget * self._breaker_over_ratio
            if compacted and over:
                st.storm_streak += 1
            elif not compacted:
                st.storm_streak = 0
            if (
                st.storm_streak >= self._breaker_trigger_runs
                and self._storm_window_low_hit(session_id)
            ):
                self._enter_breaker(st, reason=f"storm_streak={st.storm_streak}",
                                    session_id=session_id, model_ref=model_ref,
                                    chars_total=chars_total, budget=budget)
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("breaker 计数异常（fail-open）", exc_info=True)

    def _storm_window_low_hit(self, session_id: str) -> bool:
        """命中共信号: 独立滚动窗口命中率低于阈值（per-session，无样本不触发——等数据积累）."""
        try:
            win = self._breaker_hit_win.get(session_id, [])
            if len(win) < 2:  # ≥2 样本即可粗判（build 先于当轮 record，天然滞后一轮）
                return False
            tin = sum(i for i, _ in win)
            if tin <= 0:
                return False
            return (sum(h for _, h in win) / tin) < self._breaker_hit_thr
        except Exception:  # noqa: BLE001 — fail-open
            return False

    def _breaker_round_tick(
        self,
        st: _BreakerState,
        compacted: bool,
        anchor_moved: bool,
        chars_total: int,
        budget: int,
        session_id: str,
        model_ref: str,
    ) -> None:
        """breaker 内逐轮: cooldown 下限 + 退出 hysteresis（水位 + 连续稳定）."""
        st.rounds += 1
        under = (budget > 0 and chars_total <= budget * self._breaker_exit_chars_ratio) or (
            budget <= 0
        )
        if (not compacted) and (not anchor_moved) and under:
            st.clean_runs += 1
        else:
            st.clean_runs = 0
        if (
            st.rounds >= self._breaker_cooldown_rounds
            and st.clean_runs >= self._breaker_exit_stable_runs
        ):
            self._exit_breaker(st, reason="recovered",
                               session_id=session_id, model_ref=model_ref,
                               chars_total=chars_total, budget=budget)

    def breaker_active_for(self, session_id: str) -> bool:
        """该会话是否处于熔断冻结期（build 冻结压缩 + engine 压力管控）."""
        try:
            st = self._breakers.get(session_id or "")
            return bool(st and st.active)
        except Exception:  # noqa: BLE001 — fail-open
            return False

    def breaker_freeze_compression(self, session_id: str) -> bool:
        """该会话本轮是否禁止程序压缩（冻结期且未武装逃生轮）."""
        try:
            st = self._breakers.get(session_id or "")
            return bool(st and st.active and not st.pressure_escape)
        except Exception:  # noqa: BLE001 — fail-open
            return False

    def context_pressure_decision(
        self, session_id: str, chars_total: int, budget: int
    ) -> bool:
        """breaker 冻结期: 上下文超安全水位 → context_pressure（不提交）.

        安全水位 = 预算×BREAKER_PRESSURE_RATIO（默认 0.95，与 cache_guard 规则 F
        BLOCK 阈值对齐——breaker 前置拦截，规则 F 不双拦）。逃生轮放行（允许
        一次受控压缩提交）。
        """
        try:
            if not self.breaker_active_for(session_id) or budget <= 0:
                return False
            st = self._breakers.get(session_id)
            if st is not None and st.pressure_escape:
                return False
            return chars_total > budget * self._breaker_pressure_ratio
        except Exception:  # noqa: BLE001 — fail-open
            return False

    def note_context_pressure(
        self,
        session_id: str,
        *,
        reason: str,
        chars_total: int,
        budget: int,
        model_ref: str = "",
    ) -> None:
        """breaker 冻结期触发 context_pressure（engine 前置拦截后调用）.

        连续达 BREAKER_PRESSURE_ESCAPE_MAX → 武装逃生轮（允许一次受控压缩，
        防永久死锁——AI 不行动时烧损有界）。
        """
        try:
            if not session_id:
                return
            st = self._breaker(session_id)
            st.pressure_runs += 1
            st.last_chars = chars_total
            st.last_budget = budget
            self._breaker_audit(
                "context_pressure",
                session_id=session_id, model_ref=model_ref, st=st,
                chars_total=chars_total, budget=budget, reason=reason,
            )
            if st.pressure_runs >= self._breaker_pressure_escape_max:
                st.pressure_escape = True
                st.pressure_runs = 0
                self._breaker_audit(
                    "escape_armed",
                    session_id=session_id, model_ref=model_ref, st=st,
                    chars_total=chars_total, budget=budget,
                    reason=f"pressure_runs>={self._breaker_pressure_escape_max}",
                )
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("breaker context_pressure 异常（fail-open）", exc_info=True)

    def _enter_breaker(
        self, st: _BreakerState, *, reason: str, session_id: str, model_ref: str,
        chars_total: int, budget: int,
    ) -> None:
        st.active = True
        st.rounds = 0
        st.clean_runs = 0
        st.pressure_runs = 0
        st.pressure_escape = False
        st.entered_at = time.time()
        st.enter_reason = reason
        st.exit_reason = ""
        st.last_chars = chars_total
        st.last_budget = budget
        logger.warning(
            "cache_health breaker 进入（session=%s）: %s（chars=%s budget=%s）",
            session_id[:8], reason, chars_total, budget,
        )
        self._breaker_audit("breaker_enter", session_id=session_id, model_ref=model_ref,
                            st=st, chars_total=chars_total, budget=budget, reason=reason)

    def _exit_breaker(
        self, st: _BreakerState, *, reason: str, session_id: str, model_ref: str,
        chars_total: int, budget: int,
    ) -> None:
        st.active = False
        st.storm_streak = 0
        st.rounds = 0
        st.clean_runs = 0
        st.pressure_runs = 0
        st.pressure_escape = False
        st.exit_reason = reason
        logger.warning(
            "cache_health breaker 退出（session=%s）: %s（chars=%s budget=%s）",
            session_id[:8], reason, chars_total, budget,
        )
        self._breaker_audit("breaker_exit", session_id=session_id, model_ref=model_ref,
                            st=st, chars_total=chars_total, budget=budget, reason=reason)

    def _breaker_audit(
        self,
        event: str,
        *,
        session_id: str,
        model_ref: str,
        st: _BreakerState,
        chars_total: int,
        budget: int,
        reason: str,
        **extra: object,
    ) -> None:
        """审计事件落盘（append-only JSONL）: 复发可从 cache_breaker.jsonl 直接判定."""
        try:
            row = {
                "ts": datetime.now(UTC).isoformat(),
                "event": event,
                "session_id": session_id,
                "model": model_ref,
                "storm_count": st.storm_streak,
                "anchor": self._anchor_move_runs,
                "chars_total": chars_total,
                "budget": budget,
                "reason": reason,
            }
            row.update(extra)  # 事件专属字段（如 pre_chars/post_chars/drop_pct）
            path = Path(self._breaker_audit_file)  # 防御: 调用方可能直接赋值 str
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("breaker 审计写入异常（fail-open）", exc_info=True)

    def note_view_not_shrinking(
        self,
        *,
        pre_chars: int,
        post_chars: int,
        drop_pct: float,
        session_id: str = "",
        model_ref: str = "",
    ) -> None:
        """EVO-20260825 任务6.2: head_keep 大裁后视图未缩小（drop<5%）→ 审计事件.

        压缩发生但提交视图几乎没缩小 → 下一轮大概率仍超压缩线 → 压缩风暴前兆。
        写入 cache_breaker.jsonl（含 pre/post/drop 字段），复发可归因。
        """
        try:
            if not session_id:
                return
            st = self._breaker(session_id)
            self._breaker_audit(
                "view_not_shrinking_after_compact",
                session_id=session_id,
                model_ref=model_ref,
                st=st,
                chars_total=post_chars,
                budget=0,
                reason=f"pre={pre_chars} post={post_chars} drop={drop_pct:.1f}%",
                pre_chars=pre_chars,
                post_chars=post_chars,
                drop_pct=drop_pct,
            )
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("view_not_shrinking 审计异常（fail-open）", exc_info=True)

    def breaker_state(self, session_id: str = "") -> dict:
        """熔断状态快照（architecture_status/测试）."""
        try:
            out: dict[str, dict] = {}
            for sid, st in self._breakers.items():
                if session_id and sid != session_id:
                    continue
                out[sid[:12]] = {
                    "storm_streak": st.storm_streak,
                    "active": st.active,
                    "rounds": st.rounds,
                    "clean_runs": st.clean_runs,
                    "pressure_runs": st.pressure_runs,
                    "pressure_escape": st.pressure_escape,
                    "enter_reason": st.enter_reason,
                    "exit_reason": st.exit_reason,
                    "last_chars": st.last_chars,
                    "last_budget": st.last_budget,
                }
            return out
        except Exception:  # noqa: BLE001 — fail-open
            return {}

    def recent_attribution(self, session_id: str = "") -> dict | None:
        """命中率归因判定（spec §5.4.1-3，借鉴 token-optimizer-mcp 按行归因的类别级版本）.

        likely_cause ∈ {anchor_moved, gate_drift, cold_start, unknown}；
        样本不足（_win_runs < _min_runs）→ None；fail-open。
        EVO-20260825: session_id 分桶。
        """
        try:
            b = self._get_bucket(session_id)
            if b.win_runs < self._min_runs:
                return None
            rate = b.win_hit / b.win_in if b.win_in else None
            if rate is None:
                return None
            if b.anchor_moved_in_win > 0:
                cause = "anchor_moved"
            elif self._gate_drift_count > 0:
                cause = "gate_drift"
            elif b.win_runs < self._min_runs * 2:
                cause = "cold_start"  # 窗口仍在早期构建
            else:
                cause = "unknown"
            return {
                "rate": rate,
                "anchor_moved_in_win": b.anchor_moved_in_win,
                "gate_drift_count": self._gate_drift_count,
                "likely_cause": cause,
            }
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("归因判定异常（fail-open）", exc_info=True)
            return None

    def reset(self, reason: str = "", clear_buckets: bool = True) -> None:
        """显式全量重置（spec §5.4.1-3 注记，grill-me C1）.

        清空窗口/基线/归因计数/分桶；保留 _fail_alerted_sessions（跨重置有效）。
        2026-08-20 (EVO-20260820-0b96348d) 语义拆分（用户决策: 每个模型各自连续统计）:
        - clear_buckets=True（默认）: 显式重置（如 /clear 会话、诊断复位）→ 连模型桶一起清。
        - clear_buckets=False: 模型切换/新会话用轻量重置——保留桶（切回热检查、模型级
          累计统计跨会话持久，不因切换/换会话丢失）。
        EVO-20260825: 清空 session_buckets + breaker_hit_win per-session。
        """
        try:
            self._session_buckets = {}
            self._anchor_move_runs = 0
            self._system_baselines = {}
            self._tools_prev_fp = {}
            self._tools_change_count = 0
            self._gate_drift_count = 0
            self._breakers = {}  # P0: 熔断状态随重置清空（模型切换/会话变更重新判定）
            self._breaker_hit_win = {}  # P0: 命中共信号窗口同步清空
            if clear_buckets:
                self._buckets = {}
            if reason:
                logger.info("cache_health 重置: %s", reason)
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("cache_health reset 异常（fail-open）", exc_info=True)

    def reset_session(self, session_id: str) -> None:
        """EVO-20260825（任务12 §5.12）: 惰性移除指定 session 的分桶数据.

        运维清理残留 run 时调用（runner.stop）——清除该会话的命中窗口/熔断状态/
        归因计数/基线，下次该会话重新记录时从零起算（惰性：仅弹该 session key）。
        """
        try:
            self._session_buckets.pop(session_id, None)
            self._breaker_hit_win.pop(session_id, None)
            self._breakers.pop(session_id, None)
            self._system_baselines.pop(session_id, None)
            self._tools_prev_fp.pop(session_id, None)
            self._fail_alerted_sessions.discard(session_id)
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("cache_health reset_session 异常（fail-open）", exc_info=True)

    def note_new_session(self, session_id: str = "") -> None:
        """新会话首轮调用（用户决策 2026-08-20）: 只重置活动窗口 + 模型游标，保留模型桶.

        原则: 桶 = 模型生命周期统计（跨会话/跨切换持久，每个模型各自连续累计）；
        窗口 = 近期状态（新会话从零起算）；游标 _last_model_ref 复位 None——
        避免新会话首轮把上个会话的模型误判为"切换"（误报切换提示）。
        连续切换模型对话时，各模型命中率统计保持稳定连续，不受会话边界影响。
        EVO-20260825: 新会话使用独立 per-session bucket。
        """
        try:
            if session_id:
                self._session_buckets[session_id] = _SessionBucket()
            self._last_model_ref = None
            if session_id:
                logger.debug("cache_health 新会话: %s", session_id)
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("cache_health note_new_session 异常（fail-open）", exc_info=True)

    @property
    def force_head_keep(self) -> bool:
        """EVO-20260825: 任一会话处于拦截期 → True（兼容旧调用方）."""
        return any(b.force_head_keep for b in self._session_buckets.values())

    def force_head_keep_for(self, session_id: str) -> bool:
        """指定会话是否处于拦截期."""
        b = self._session_buckets.get(session_id)
        return bool(b and b.force_head_keep)

    # ── 发送前门禁（preflight/postcheck，程序常态锚点管理，per-session 基线）──
    def preflight(
        self, session_id: str, system_fp: str, tools_fp: str = ""
    ) -> None:
        """发送前预检: system 轴指纹与该 session 基线不符 → 强制缓存友好压缩.

        双轴语义（契约 §3/§7 不变式第 3 条）:
        - system 轴独变 = 真漂移 → force_head_keep + drift 计数 + 观测标记；
        - tools 轴独变 = 合法变更（schema/顺序变化）→ 不干预不计 drift（归因走调用点轴埋点）。
        合规化动作（当次 build 即生效，锚点不动 → 前缀恢复稳定）。fail-open。
        EVO-20260825: per-session 分桶——force_head_keep 写回对应会话 bucket。
        """
        _ = tools_fp  # 形参在位（§9.1 统一双轴面）；tools 轴不在 preflight 干预面
        try:
            prev = self._system_baselines.get(session_id)
            if prev is not None and system_fp != prev:
                b = self._get_bucket(session_id)
                b.force_head_keep = True
                self._gate_drift_count += 1
                b.gate_note_pending = True  # 漂移干预 → 一次性观测标记待消费（R8.11 不进 prompt）
        except Exception:  # noqa: BLE001
            logger.warning("门禁预检异常（fail-open）", exc_info=True)

    def postcheck(
        self, session_id: str, system_fp: str, tools_fp: str = ""
    ) -> str | None:
        """发送前校验: system 轴一致 → 出闸；system 变 → 漂移提示 + 建新基线；tools 变 → 计数不提示.

        首次（无基线）直接建立基线。fail-open 不阻断发送（门禁是管理不是熔断）。
        tools 轴独变 = 合法变更（§10 Q2 已决）：仅 _tools_change_count 计数 + logger，
        不进 snapshot、不出提示、不触发干预。
        """
        try:
            prev = self._system_baselines.get(session_id)
            prev_tools = self._tools_prev_fp.get(session_id)
            self._system_baselines[session_id] = system_fp  # 总是更新为最新（漂移即新基线）
            if tools_fp:
                self._tools_prev_fp[session_id] = tools_fp
            if prev is None:
                return None
            if system_fp != prev:
                self._gate_drift_count += 1
                return (
                    "[拼装合规提示] 发送前检测到前缀漂移（system 轴变化），已记录并强制"
                    "后续压缩保留锚点头部；本请求不受影响。"
                )
            if tools_fp and prev_tools and tools_fp != prev_tools:
                self._tools_change_count += 1
                logger.info(
                    "门禁后检: tools 轴变更（合法，不干预）session=%s 累计#%d",
                    session_id,
                    self._tools_change_count,
                )
            return None
        except Exception:  # noqa: BLE001
            logger.warning("门禁后检异常（fail-open）", exc_info=True)
            return None

    def take_gate_note(self, session_id: str = "") -> bool:
        """Consume the one-shot cache-gate observability marker.

        R8.11: live build no longer turns this marker into prompt text.  The bool remains
        for monitor state, action telemetry and legacy err1210 defer compatibility.
        EVO-20260825: per-session buckets keep consumption session-scoped.
        """
        try:
            b = self._get_bucket(session_id)
            if b.gate_note_pending:
                b.gate_note_pending = False
                return True
            return False
        except Exception:  # noqa: BLE001
            logger.debug("知情标记消费异常（fail-open）", exc_info=True)
            return False

    def restore_gate_note(self, session_id: str = "") -> None:
        """Restore a legacy/deferred cache-gate marker (compatibility only).

        R8.11 live build consumes restored markers as observability-only state and does not
        re-inject ``GATE_NOTE_CONTENT``.  The API remains for old err1210 snapshots/defer
        records and is idempotent.  Fail-open: missing buckets are created lazily.
        """
        try:
            self._get_bucket(session_id).gate_note_pending = True
        except Exception:  # noqa: BLE001
            logger.debug("知情标记置回异常（fail-open）", exc_info=True)

    # ── 状态快照（可观测/测试）──
    def snapshot(self, session_id: str = "") -> dict:
        """EVO-20260825: per-session 快照——session_id 非空返回该分桶快照，
        为空返回聚合快照 + 惰性清理超 1h 无活跃的分桶。
        """
        try:
            _now = time.time()
            if session_id:
                b = self._get_bucket(session_id)
                return {
                    "win_in": b.win_in,
                    "win_hit": b.win_hit,
                    "win_runs": b.win_runs,
                    "alerted": b.alerted,
                    "good_streak": b.good_streak,
                    "anchor_move_runs": self._anchor_move_runs,
                    "anchor_moved_in_win": b.anchor_moved_in_win,
                    "anchor_moved_since_record": b.anchor_moved_since_record,
                    "force_head_keep": b.force_head_keep,
                    "fail_alerted": session_id in self._fail_alerted_sessions,
                    "recovery_timeout_runs": self._recovery_timeout_runs,
                    "gate_drift_count": self._gate_drift_count,
                    "gate_note_pending": b.gate_note_pending,
                    "baselines": dict(self._system_baselines),
                    "buckets": {k: dict(v) for k, v in self._buckets.items()},
                    "breakers": self.breaker_state(session_id),
                    "breaker_trigger_runs": self._breaker_trigger_runs,
                }
            # 聚合快照 + 惰性清理超 1h 无活跃分桶
            _dead_sids: list[str] = []
            for sid, bucket in self._session_buckets.items():
                if (not self._breakers.get(sid) and
                        _now - bucket.last_update_ts > 3600):
                    _dead_sids.append(sid)
            for _sid in _dead_sids:
                self._session_buckets.pop(_sid, None)
                self._breaker_hit_win.pop(_sid, None)
                self._fail_alerted_sessions.discard(_sid)
            sessions = {}
            for sid, bucket in self._session_buckets.items():
                sessions[sid[:12]] = {
                    "win_in": bucket.win_in,
                    "win_hit": bucket.win_hit,
                    "win_runs": bucket.win_runs,
                    "alerted": bucket.alerted,
                    "force_head_keep": bucket.force_head_keep,
                    "trend": self._trend_summary(bucket),  # EVO-20260827-ad73251b
                }
            _agg = _SessionBucket()
            for bucket in self._session_buckets.values():
                _agg.win_in += bucket.win_in
                _agg.win_hit += bucket.win_hit
                _agg.win_runs += bucket.win_runs
                _agg.alerted = _agg.alerted or bucket.alerted
                _agg.force_head_keep = _agg.force_head_keep or bucket.force_head_keep
                _agg.good_streak = max(_agg.good_streak, bucket.good_streak)
                _agg.anchor_moved_in_win += bucket.anchor_moved_in_win
                _agg.anchor_moved_since_record = (
                    _agg.anchor_moved_since_record or bucket.anchor_moved_since_record
                )
                _agg.gate_note_pending = _agg.gate_note_pending or bucket.gate_note_pending
            return {
                # 兼容旧快照字段（聚合视角）
                "win_in": _agg.win_in,
                "win_hit": _agg.win_hit,
                "win_runs": _agg.win_runs,
                "alerted": _agg.alerted,
                "good_streak": _agg.good_streak,
                "force_head_keep": _agg.force_head_keep,
                "anchor_moved_in_win": _agg.anchor_moved_in_win,
                "anchor_moved_since_record": _agg.anchor_moved_since_record,
                "gate_note_pending": _agg.gate_note_pending,
                "fail_alerted": len(self._fail_alerted_sessions) > 0,
                "all_sessions_hit_rate": sum(
                    b.win_hit for b in self._session_buckets.values()
                ) / max(1, sum(b.win_in for b in self._session_buckets.values())),
                "sessions": sessions,
                "anchor_move_runs": self._anchor_move_runs,
                "gate_drift_count": self._gate_drift_count,
                "baselines": dict(self._system_baselines),
                "buckets": {k: dict(v) for k, v in self._buckets.items()},
                "breakers": self.breaker_state(),
                "breaker_trigger_runs": self._breaker_trigger_runs,
                "fail_alerted_sessions": list(self._fail_alerted_sessions),
                "session_count": len(self._session_buckets),
            }
        except Exception:  # noqa: BLE001 — fail-open
            return {"error": "snapshot fail-open"}
