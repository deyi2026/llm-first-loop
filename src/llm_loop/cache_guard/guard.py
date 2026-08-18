"""cache_guard 规则引擎（5 类规则——前缀稳定工程保证）.

校验输入（请求组装后、发送前）:
- system_text: 本次 system prompt（str）
- system_baseline: 该会话稳定基线（首次无则建立）
- messages: 提交消息序列（list[dict]——role/content）
- tools_schema: 工具定义（list[dict]）
- meta: {session_id, provider, model, run_round, compress_count_this_run}

决策:
- ALLOW: 放行（无规则命中）
- BLOCK: 拦截（可修复/隐私——调用方决定：修复或终止）
- WARN: 记录 + 提示（fail-open——不阻断）

审计: data/audit/guarded_requests.jsonl（全量请求——账单对账闭合）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 规则配置（初始保守——可调） ──
_SYSTEM_DIFF_WARN_THRESHOLD = 40  # system 相对基线变化字符数（超→WARN）
_TOOL_RESULT_MAX_CHARS = 200_000  # 单条工具结果上限（超→WARN 归档提示）
_COMPRESS_STORM_PER_RUN = 10  # 单 run 压缩次数上限（超→WARN）
# 规则 F（2026-08-18 用户反馈'不应出去的'）：提交体积占比——
# 消息总字符 / 预算 > 阈值 → BLOCK（先压缩 checkpoint 或换会话——避免注定低命中的请求出去）
_SUBMIT_RATIO_BLOCK = 0.95  # >95% 预算 → BLOCK（强制先决策）
_SUBMIT_RATIO_WARN = 0.85  # >85% → WARN（提示接近超限）
# 规则 G（2026-08-18 用户反馈：'低命中'应拦截——命中是结果——需响应回馈闭环）：
# 会话近期命中率 < 阈值且样本足够 → BLOCK（前缀不稳定——先压缩 checkpoint/换会话）
# 阈值 env 化（拷问④——2026-08-18）: 可用 CACHE_GUARD_* 覆盖
_HIT_RATE_BLOCK = float(os.environ.get("CACHE_GUARD_HIT_BLOCK", "0.30"))
_HIT_RATE_WARN = float(os.environ.get("CACHE_GUARD_HIT_WARN", "0.50"))
_HIT_SAMPLE_MIN = int(os.environ.get("CACHE_GUARD_HIT_SAMPLE", "3"))
# 逃生（拷问③——2026-08-18）: 连续 BLOCK N 次后自动降级 WARN（防死锁——AI 不处理时
# 不无限拦截；降级后 AI 可行动）
_BLOCK_ESCAPE_MAX = int(os.environ.get("CACHE_GUARD_BLOCK_ESCAPE", "3"))
_SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),  # API key
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS key
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),  # GitHub token
    re.compile(r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"),  # 私钥
]
_SENSITIVE_ENV_NAMES = {"DEEPSEEK_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "KIMI_API_KEY", "MINIMAX_API_KEY"}


@dataclass
class GuardDecision:
    verdict: str  # ALLOW / BLOCK / WARN
    rule: str = ""  # 命中的规则 id
    detail: str = ""
    audit: dict = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.verdict != "BLOCK"


def _stable_fp(system_text: str) -> str:
    return hashlib.sha256(system_text.encode("utf-8")).hexdigest()


def _check_system_stability(system_text: str, baseline: str | None) -> GuardDecision | None:
    """规则 A: system 稳定性——与基线 diff（超阈值 WARN）.

    DSH 借鉴（2026-08-18 拷问产出）: checkpoint rejection 语义的轻量版——
    发送前检测前缀漂移 → 提示（AI 决策：接受断点 or 先压缩 checkpoint 再发）.
    """
    if not baseline:
        return None  # 首次——建立基线（无基线不判）
    if system_text == baseline:
        return None  # 字节一致——稳定 ✓
    # 变化量（简化：长度差 + 内容差）
    diff = abs(len(system_text) - len(baseline))
    if diff >= _SYSTEM_DIFF_WARN_THRESHOLD:
        return GuardDecision(
            verdict="WARN",
            rule="system_stability",
            detail=(
                f"system 相对基线变化 {diff} 字符（缓存前缀将失效——开发变更/动态注入？）。"
                "DSH 语义：可先触发压缩 checkpoint（前缀重建）再发——或接受本次断点（下次恢复稳定）"
            ),
        )
    return None


def _check_injection_discipline(messages: list[dict]) -> GuardDecision | None:
    """规则 B: 注入纪律——非首位 system 消息（中间注入/重排→前缀断）.

    2026-08-18 system 静态化后: 提交层非首个 system 自动转 user——正常路径不触发。
    保留为【防御性】规则: 若未来某处绕过转 user（直接塞 system 进序列）仍告警——
    防前缀破坏回归（对齐 DSH: system 主体必须字节静态——注入一律独立消息）。
    """
    for i, m in enumerate(messages):
        if m.get("role") == "system" and i != 0:
            return GuardDecision(
                verdict="WARN",
                rule="injection_discipline",
                detail=f"第 {i} 条消息是 system（非首位——中间注入/重排——前缀断风险；提交层应已转 user）",
            )
    return None


def _check_tool_results(messages: list[dict]) -> GuardDecision | None:
    """规则 C: 工具结果体积——超长未归档（提示 WARN）."""
    for i, m in enumerate(messages):
        if m.get("role") == "tool":
            c = m.get("content") or ""
            if len(c) > _TOOL_RESULT_MAX_CHARS:
                return GuardDecision(
                    verdict="WARN",
                    rule="tool_result_size",
                    detail=f"工具结果 {len(c):,} 字符 > {_TOOL_RESULT_MAX_CHARS:,}（建议先归档再提交——前缀体积）",
                )
    return None


def _check_compress_storm(meta: dict) -> GuardDecision | None:
    """规则 D: 窗口漂移——单 run 压缩次数（压缩风暴→前缀持续断）."""
    n = int(meta.get("compress_count_this_run") or 0)
    if n > _COMPRESS_STORM_PER_RUN:
        return GuardDecision(
            verdict="WARN",
            rule="compress_storm",
            detail=f"本 run 已压缩 {n} 次（>{_COMPRESS_STORM_PER_RUN}——窗口持续漂移——前缀持续断）",
        )
    return None


def _check_submit_ratio(messages: list[dict], meta: dict) -> GuardDecision | None:
    """规则 F（2026-08-18）: 提交体积占比——历史接近预算上限时注定低命中（压缩在即）.

    DSH checkpoint rejection 语义的完整版：发送前检查"前缀可持久性"——
    占比 >95% 预算 → BLOCK（先压缩 checkpoint / 换会话——再发）；
    >85% → WARN（提示接近超限——AI 决策提前处理）。
    """
    budget = int(meta.get("history_budget") or 0)
    if budget <= 0:
        return None
    total_chars = sum(len(str(m.get("content") or "")) for m in messages)
    ratio = total_chars / budget
    if ratio > _SUBMIT_RATIO_BLOCK:
        return GuardDecision(
            verdict="BLOCK",
            rule="submit_ratio",
            detail=(
                f"提交 {total_chars:,} 字符 = 预算 {budget:,} 的 {ratio*100:.0f}%"
                f"（>{_SUBMIT_RATIO_BLOCK*100:.0f}%——压缩在即——本次请求注定低命中全价）。"
                "建议：先压缩 checkpoint 或换新会话再发（DSH checkpoint rejection 语义）"
            ),
        )
    if ratio > _SUBMIT_RATIO_WARN:
        return GuardDecision(
            verdict="WARN",
            rule="submit_ratio",
            detail=f"提交占比 {ratio*100:.0f}%（>{_SUBMIT_RATIO_WARN*100:.0f}%——接近超限——建议提前压缩/换会话）",
        )
    return None


def _check_privacy(messages: list[dict], system_text: str) -> GuardDecision | None:
    """规则 E: 隐私泄漏——API key/私钥/敏感 env 值进 prompt（硬拦截）."""
    blob = system_text + "\n" + "\n".join(str(m.get("content") or "") for m in messages[:3])
    for pat in _SENSITIVE_PATTERNS:
        if pat.search(blob):
            return GuardDecision(
                verdict="BLOCK",
                rule="privacy_leak",
                detail=f"检测到敏感模式 {pat.pattern[:20]}…（API key/私钥泄漏——拦截）",
            )
    # 敏感 env 值比对
    for name in _SENSITIVE_ENV_NAMES:
        val = os.environ.get(name, "")
        if val and len(val) > 8 and val in blob:
            return GuardDecision(
                verdict="BLOCK",
                rule="privacy_leak",
                detail=f"prompt 含环境变量 {name} 的值（泄漏——拦截）",
            )
    return None


def validate_request(
    *,
    system_text: str,
    messages: list[dict],
    baseline: str | None = None,
    meta: dict | None = None,
    audit_file: str | Path | None = None,
) -> GuardDecision:
    """请求前校验（唯一出入口核心）——5 类规则——fail-open（校验失败不阻断）.

    审计: 全量请求记录（guarded_requests.jsonl——账单对账闭合）。
    """
    meta = meta or {}
    decision = GuardDecision(verdict="ALLOW")
    try:
        for check in (
            lambda: _check_system_stability(system_text, baseline),
            lambda: _check_injection_discipline(messages),
            lambda: _check_tool_results(messages),
            lambda: _check_compress_storm(meta),
            lambda: _check_submit_ratio(messages, meta),
            lambda: _check_privacy(messages, system_text),
        ):
            r = check()
            if r is None:
                continue
            # 优先级: BLOCK > WARN（首条命中记录——ALLOW 继续）
            if r.verdict == "BLOCK":
                decision = r
                break
            if decision.verdict == "ALLOW":
                decision = r
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("cache_guard 校验异常（fail-open 放行）", exc_info=True)
        decision = GuardDecision(verdict="ALLOW", detail="guard 异常 fail-open")

    # 审计落盘（全量——对账闭合）
    decision.audit = {
        "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "session_id": meta.get("session_id", ""),
        "provider": meta.get("provider", ""),
        "model": meta.get("model", ""),
        "run_round": meta.get("run_round"),
        "system_fp": _stable_fp(system_text)[:16],
        "messages": len(messages),
        "tools": len(meta.get("tools", []) or []),
        "verdict": decision.verdict,
        "rule": decision.rule,
        "detail": decision.detail,
    }
    try:
        path = Path(audit_file) if audit_file else (
            Path(os.environ.get("LFL_DATA_DIR", "")) / "audit" / "guarded_requests.jsonl"
            if os.environ.get("LFL_DATA_DIR")
            else Path(__file__).resolve().parents[3] / "data" / "audit" / "guarded_requests.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(decision.audit, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 审计失败不影响决策
        logger.debug("cache_guard 审计写入失败（fail-open）")
    return decision


class CacheGuardBlockedError(Exception):
    """cache_guard BLOCK 专用异常（拷问⑥——2026-08-18）: 与普通 LLM 错误区分——

    engine 直接如实反馈 AI（不重试/不走 overflow reinject——重试同样被拦=浪费循环）.
    """


class PromptGuard:
    """MCP 出入口的进程内接口（校验 + 基线维护 + 命中率闭环）——MCP server 复用本类."""

    def __init__(self, audit_file: str | Path | None = None) -> None:
        self._baselines: dict[str, str] = {}  # session_id → system fp
        self.audit_file = audit_file
        # 规则 G: 会话级命中率窗口（近 N 次请求的 hit/in——响应回馈）
        self._hit_win: dict[str, list[tuple[int, int]]] = {}  # session → [(in, hit)...]
        # 逃生（拷问③）: 每会话连续 BLOCK 计数——达上限自动降级 WARN
        self._block_streak: dict[str, int] = {}

    def reset_session(self, session_id: str) -> None:
        """重置会话状态（拷问②——模型切换/换会话时调用）——清窗口/基线/逃生计数. """
        try:
            self._hit_win.pop(session_id, None)
            self._baselines.pop(session_id, None)
            self._block_streak.pop(session_id, None)
        except Exception:  # noqa: BLE001
            pass

    def record_result(self, session_id: str, tokens_in: int, tokens_hit: int) -> None:
        """响应后回馈（闭环）——记录该会话本次请求的命中——规则 G 数据源.

        fail-open：记录失败不影响请求。
        """
        try:
            if tokens_in <= 0:
                return
            win = self._hit_win.setdefault(session_id, [])
            win.append((tokens_in, tokens_hit))
            if len(win) > 10:
                del win[:-10]  # 窗口最近 10 次
        except Exception:  # noqa: BLE001
            logger.debug("guard record_result 失败（fail-open）")

    def _recent_hit_rate(self, session_id: str) -> float | None:
        """该会话近期命中率（窗口样本不足返回 None——不判）. """
        win = self._hit_win.get(session_id) or []
        if len(win) < _HIT_SAMPLE_MIN:
            return None
        ti = sum(i for i, _ in win)
        hi = sum(h for _, h in win)
        return (hi / ti) if ti > 0 else None

    def _check_hit_rate(self, session_id: str) -> GuardDecision | None:
        """规则 G: 近期命中率低 → 拦截——但【区分冷启动 vs 持续异常】.

        2026-08-18 用户反馈（'第一条新信息命中率肯定低'）:
        - 冷启动（前缀在构建——in 递增）低命中 = 预期——不拦（降级 WARN）
        - 前缀稳定（最近两次 in 相近——同前缀）却低命中 = 异常——BLOCK
        """
        win = self._hit_win.get(session_id) or []
        if len(win) < _HIT_SAMPLE_MIN:
            return None  # 样本不足（含新会话第一条）——不判
        rate = self._recent_hit_rate(session_id)
        if rate is None:
            return None
        # 前缀稳定性：最近两次请求的 in 是否相近（±15%——同前缀应命中）
        last_in = [i for i, _ in win[-2:]]
        prefix_stable = (
            len(last_in) == 2
            and last_in[1] > 0
            and abs(last_in[1] - last_in[0]) / last_in[1] < 0.15
        )
        if rate < _HIT_RATE_BLOCK:
            if prefix_stable:
                return GuardDecision(
                    verdict="BLOCK",
                    rule="low_hit_rate",
                    detail=(
                        f"该会话近期命中率 {rate*100:.0f}%（<{_HIT_RATE_BLOCK*100:.0f}%——"
                        "前缀稳定（最近两次 in 相近）却持续低命中——前缀漂移/压缩风暴）。"
                        "建议：先压缩 checkpoint / 换新会话 / 排查前缀漂移——再发"
                    ),
                )
            # 冷启动（前缀在构建——in 递增）——预期低——不拦（仅 WARN 知悉）
            return GuardDecision(
                verdict="WARN",
                rule="low_hit_rate",
                detail=(
                    f"近期命中率 {rate*100:.0f}%（冷启动/前缀构建中——预期低——"
                    "前缀稳定后将回升；若持续请排查）"
                ),
            )
        if rate < _HIT_RATE_WARN:
            return GuardDecision(
                verdict="WARN",
                rule="low_hit_rate",
                detail=f"该会话近期命中率 {rate*100:.0f}%（<{_HIT_RATE_WARN*100:.0f}%——注意前缀稳定性）",
            )
        return None

    def check(
        self,
        *,
        session_id: str,
        system_text: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        run_round: int | None = None,
        compress_count_this_run: int = 0,
    ) -> GuardDecision:
        baseline = self._baselines.get(session_id)
        decision = validate_request(
            system_text=system_text,
            messages=messages,
            baseline=baseline,
            meta={
                "session_id": session_id,
                "provider": "openai-compat",
                "model": "",
                "run_round": run_round,
                "tools": tools or [],
                "compress_count_this_run": compress_count_this_run,
            },
            audit_file=self.audit_file,
        )
        # 规则 G: 低命中拦截（优先级高于普通 WARN——命中是结果闭环）
        if decision.verdict == "ALLOW" or decision.verdict == "WARN":
            hit_d = self._check_hit_rate(session_id)
            if hit_d is not None and (
                hit_d.verdict == "BLOCK"
                or (hit_d.verdict == "WARN" and decision.verdict == "ALLOW")
            ):
                # 逃生（拷问③）: 连续 BLOCK 达上限 → 降级 WARN（防死锁——AI 不处理时
                # 不无限拦截——AI 可行动（压缩/换会话）后重试）
                if hit_d.verdict == "BLOCK":
                    streak = self._block_streak.get(session_id, 0) + 1
                    self._block_streak[session_id] = streak
                    if streak > _BLOCK_ESCAPE_MAX:
                        hit_d = GuardDecision(
                            verdict="WARN",
                            rule="low_hit_rate_escape",
                            detail=(
                                f"连续 {streak} 次 BLOCK 后自动降级 WARN（逃生——"
                                "避免死锁；请尽快压缩 checkpoint/换会话恢复命中）"
                            ),
                        )
                else:
                    self._block_streak[session_id] = 0
                decision = hit_d
        elif decision.verdict == "ALLOW":
            self._block_streak[session_id] = 0
        # 基线维护：ALLOW 且无 WARN（system 稳定）时更新基线；有 WARN 不动（下次继续检测）
        if decision.verdict == "ALLOW":
            self._baselines[session_id] = system_text
        return decision
