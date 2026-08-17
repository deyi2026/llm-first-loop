"""EVO-20260817-72fcd94a: 缓存健康闭环（独立模块，控制 engine.py 体量）.

程序常态锚点管理（用户 2026-08-17 决策）:
- 发送前门禁: preflight 发现前缀/锚点漂移 → 强制缓存友好压缩（保留锚点头部）→ 合规化;
  postcheck 确认本次发送前缀与基线一致 → 出闸（不合规只审计 + 提示，fail-open 不阻断 run）。
- 窗口兜底: 命中率窗口（≥5 run 且 ≥50K tokens）低 <50% → 告警注入 + 拦截;
  恢复: 拦截后连续 5 轮单轮命中率 ≥80% → 解除 + 复位（可再次告警）。
所有方法 fail-open，异常不影响主循环。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# EVO-20260817-72fcd94a: 门禁干预知情标记（固定文本，一次性注入 built 末尾——缓存友好，
# 不破坏前缀；让 AI 感知本轮上下文结构变化，消除困惑）
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
    ) -> None:
        # 窗口状态
        self._win_in = 0
        self._win_hit = 0
        self._win_runs = 0
        self._alerted = False
        self._good_streak = 0
        # 归因 + 拦截
        self._anchor_move_runs = 0
        self._force_head_keep = False
        # 发送前门禁（per-session 基线: 不同会话注入/记忆不同，互不干扰）
        self._baselines: dict[str, str] = {}  # session_id → 稳定段指纹（system+注入）
        self._gate_drift_count = 0
        self._gate_note_pending = False  # 知情标记待注入（干预激活首轮一次性）
        # 参数
        self._min_runs = min_runs
        self._min_tokens = min_tokens
        self._alert_thr = alert_thr
        self._recover_thr = recover_thr
        self._force_head_ratio = force_head_ratio

    # ── 窗口监控（run 末尾调用）──
    def record(self, tokens_in: int, tokens_hit: int) -> str | None:
        """累计窗口并做告警/恢复判定，返回注入提示或 None（fail-open）."""
        try:
            self._win_in += tokens_in
            self._win_hit += tokens_hit
            self._win_runs += 1
            rate = self._win_hit / self._win_in if self._win_in else 1.0
            if self._alerted or self._force_head_keep:
                single_rate = tokens_hit / tokens_in if tokens_in else 1.0
                self._good_streak = (
                    self._good_streak + 1 if single_rate >= self._recover_thr else 0
                )
                if self._good_streak >= self._min_runs:
                    _runs, _hit, _in = self._win_runs, self._win_hit, self._win_in
                    self._alerted = False
                    self._force_head_keep = False
                    self._reset_window()
                    self._good_streak = 0
                    self._anchor_move_runs = 0
                    return (
                        f"[缓存已恢复] 命中率连续 {self._min_runs} 轮 ≥{self._recover_thr*100:.0f}%"
                        f"（近 {_runs} 次 run {_hit}/{_in} tokens），锚点已对齐，解除强制缓存友好"
                        "压缩，恢复正常监控。"
                    )
                return None
            if (
                self._win_runs >= self._min_runs
                and self._win_in >= self._min_tokens
                and rate < self._alert_thr
            ):
                cause = (
                    "近窗口内压缩锚点前移破坏前缀"
                    if self._anchor_move_runs
                    else "前缀可能被破坏（动态注入 system/每轮内容变更）"
                )
                self._alerted = True
                self._force_head_keep = True
                self._gate_note_pending = True  # 干预激活 → 知情标记待注入（本轮 build 消费）
                self._reset_window()  # 拦截开始: 只看拦截后表现
                return (
                    f"[缓存命中告警] 近 {self._win_runs} 次 run 命中率 {rate*100:.0f}%"
                    f"（{self._win_hit}/{self._win_in} tokens）。{cause}。"
                    "已拦截：后续压缩强制缓存友好（保留锚点头部，前缀稳定）；"
                    f"命中率回升至 {self._recover_thr*100:.0f}% 自动解除。"
                    "成本放大 ~50 倍（hit 0.05/M vs miss 1.5/M）。"
                )
            return None
        except Exception:  # noqa: BLE001 — fail-open
            logger.warning("缓存窗口监控异常（fail-open）", exc_info=True)
            return None

    def _reset_window(self) -> None:
        self._win_in = self._win_hit = self._win_runs = 0

    def note_anchor_moved(self) -> None:
        """build 时锚点实际前移 → 记入归因（压缩破坏前缀证据）."""
        try:
            self._anchor_move_runs += 1
        except Exception:  # noqa: BLE001
            logger.debug("anchor_move 计数异常（fail-open）", exc_info=True)

    @property
    def force_head_keep(self) -> bool:
        return self._force_head_keep

    # ── 发送前门禁（preflight/postcheck，程序常态锚点管理，per-session 基线）──
    def preflight(self, session_id: str, stable_fp: str) -> None:
        """发送前预检: 本次稳定段（system+注入）指纹与该 session 基线不符 → 强制缓存友好压缩.

        合规化动作（当次 build 即生效，锚点不动 → 前缀恢复稳定）。
        """
        try:
            prev = self._baselines.get(session_id)
            if prev is not None and stable_fp != prev:
                self._force_head_keep = True
                self._gate_drift_count += 1
                self._gate_note_pending = True  # 漂移干预 → 知情标记待注入
        except Exception:  # noqa: BLE001
            logger.warning("门禁预检异常（fail-open）", exc_info=True)

    def postcheck(self, session_id: str, stable_fp: str) -> str | None:
        """发送前校验: 本次稳定段与该 session 基线一致 → 出闸；不一致 → 提示 + 建新基线.

        首次（无基线）直接建立基线。fail-open 不阻断发送（门禁是管理不是熔断）。
        """
        try:
            prev = self._baselines.get(session_id)
            self._baselines[session_id] = stable_fp  # 总是更新为最新（受控变化即新基线）
            if prev is None:
                return None
            if stable_fp != prev:
                self._gate_drift_count += 1
                return (
                    "[拼装合规提示] 发送前检测到前缀漂移（锚点/注入变化），已记录并强制"
                    "后续压缩保留锚点头部；本请求不受影响。"
                )
            return None
        except Exception:  # noqa: BLE001
            logger.warning("门禁后检异常（fail-open）", exc_info=True)
            return None

    def take_gate_note(self) -> bool:
        """一次性消费知情标记（干预激活首轮 build 注入一次，消费后不再重复）."""
        try:
            if self._gate_note_pending:
                self._gate_note_pending = False
                return True
            return False
        except Exception:  # noqa: BLE001
            logger.debug("知情标记消费异常（fail-open）", exc_info=True)
            return False

    # ── 状态快照（可观测/测试）──
    def snapshot(self) -> dict:
        return {
            "win_in": self._win_in,
            "win_hit": self._win_hit,
            "win_runs": self._win_runs,
            "alerted": self._alerted,
            "good_streak": self._good_streak,
            "anchor_move_runs": self._anchor_move_runs,
            "force_head_keep": self._force_head_keep,
            "gate_drift_count": self._gate_drift_count,
            "gate_note_pending": self._gate_note_pending,
            "baselines": dict(self._baselines),
        }
