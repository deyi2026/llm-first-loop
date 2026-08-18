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
        recovery_timeout_runs: int = 20,
    ) -> None:
        # 窗口状态
        self._win_in = 0
        self._win_hit = 0
        self._win_runs = 0
        self._alerted = False
        self._good_streak = 0
        # 归因 + 拦截
        self._anchor_move_runs = 0
        self._anchor_moved_in_win = 0  # 窗口内锚点前移次数（归因判定：>0 破坏型，=0 设计型）
        self._anchor_moved_since_record = False  # 上次 record 后锚点是否前移（拦截期逐轮判定）
        self._force_head_keep = False
        self._fail_alerted = False  # 恢复失败已提示（每进程一次，防刷屏）
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
        self._recovery_timeout_runs = recovery_timeout_runs

    # ── 窗口监控（run 末尾调用）──
    def record(self, tokens_in: int, tokens_hit: int) -> str | None:
        """累计窗口并做告警/恢复判定，返回注入提示或 None（fail-open）.

        归因判定（2026-08-17 DSH 043）:
        - 破坏型（窗口内锚点前移 > 0）: 低命中 → 告警 + 拦截（保留头部可救回前缀）。
        - 设计型（窗口内锚点前移 = 0）: 低命中为设计值（小窗口物理决定），只观察不拦截。
        恢复（不再依赖命中率回升——设计 8% 达不到 80%，原条件死锁）:
        - 拦截期锚点未再前移连续 min_runs 轮 → 解除。
        - 超时兜底: 拦截期累计 recovery_timeout_runs 轮未恢复 → 恢复失败短消息 + 解除
          （每进程一次，防刷屏）。
        """
        try:
            self._win_in += tokens_in
            self._win_hit += tokens_hit
            self._win_runs += 1
            rate = self._win_hit / self._win_in if self._win_in else 1.0
            if self._alerted or self._force_head_keep:
                # 拦截期: 本轮锚点未前移 → 前缀已稳定，连续计数；本轮前移 → 重置
                moved_this_round = self._anchor_moved_since_record
                self._anchor_moved_since_record = False
                self._good_streak = (
                    self._good_streak + 1 if not moved_this_round else 0
                )
                if self._good_streak >= self._min_runs:
                    _runs, _hit, _in = self._win_runs, self._win_hit, self._win_in
                    self._alerted = False
                    self._force_head_keep = False
                    self._reset_window()
                    self._good_streak = 0
                    self._anchor_move_runs = 0
                    return (
                        f"[缓存已恢复] 拦截期锚点未再前移（连续 {self._min_runs} 轮），"
                        f"前缀已稳定（近 {_runs} 次 run {_hit}/{_in} tokens），解除强制"
                        "缓存友好压缩，恢复正常监控。"
                    )
                if (
                    self._win_runs >= self._recovery_timeout_runs
                    and not self._fail_alerted
                ):
                    self._fail_alerted = True
                    self._alerted = False
                    self._force_head_keep = False
                    self._reset_window()
                    self._good_streak = 0
                    self._anchor_move_runs = 0
                    return (
                        f"[缓存恢复失败] 拦截 {self._recovery_timeout_runs} 轮命中率未回升"
                        f"（当前 {rate*100:.0f}%）。请查 architecture_status 定位原因"
                        "（预算/锚点/注入）；设计行为可确认接受（本进程仅提示一次）。"
                    )
                return None
            if (
                self._win_runs >= self._min_runs
                and self._win_in >= self._min_tokens
                and rate < self._alert_thr
            ):
                if self._anchor_moved_in_win == 0 or self._fail_alerted:
                    # 设计型（锚点未前移，低命中为设计值）或已提示过恢复失败 →
                    # 只观察不告警不拦截（防噪音/刷屏）
                    return None
                cause = "近窗口内压缩锚点前移破坏前缀"
                # 告警文案快照（reset 前）——EVO-20260817-5b991577 缺陷1:
                # 原实现先 _reset_window() 再组装文案 → 显示"近 0 次 run 0/0 tokens"失真
                _runs, _hit, _in = self._win_runs, self._win_hit, self._win_in
                self._alerted = True
                self._force_head_keep = True
                self._gate_note_pending = True  # 干预激活 → 知情标记待注入（本轮 build 消费）
                self._reset_window()  # 拦截开始: 只看拦截后表现
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

    def _reset_window(self) -> None:
        self._win_in = self._win_hit = self._win_runs = 0
        self._anchor_moved_in_win = 0
        self._anchor_moved_since_record = False  # 复位即消费，防激活轮残留污染拦截期首轮判定

    def note_anchor_moved(self) -> None:
        """build 时锚点实际前移 → 记入归因（压缩破坏前缀证据）."""
        try:
            self._anchor_move_runs += 1
            self._anchor_moved_in_win += 1
            self._anchor_moved_since_record = True
        except Exception:  # noqa: BLE001
            logger.debug("anchor_move 计数异常（fail-open）", exc_info=True)

    def recent_attribution(self) -> dict | None:
        """命中率归因判定（spec §5.4.1-3，借鉴 token-optimizer-mcp 按行归因的类别级版本）.

        likely_cause ∈ {anchor_moved, gate_drift, cold_start, unknown}；
        样本不足（_win_runs < _min_runs）→ None；fail-open。
        """
        try:
            if self._win_runs < self._min_runs:
                return None
            rate = self._win_hit / self._win_in if self._win_in else None
            if rate is None:
                return None
            if self._anchor_moved_in_win > 0:
                cause = "anchor_moved"
            elif self._gate_drift_count > 0:
                cause = "gate_drift"
            elif self._win_runs < self._min_runs * 2:
                cause = "cold_start"  # 窗口仍在早期构建
            else:
                cause = "unknown"
            return {
                "rate": rate,
                "anchor_moved_in_win": self._anchor_moved_in_win,
                "gate_drift_count": self._gate_drift_count,
                "likely_cause": cause,
            }
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("归因判定异常（fail-open）", exc_info=True)
            return None

    def reset(self, reason: str = "") -> None:
        """模型切换/会话变更窗口重置（spec §5.4.1-3 注记，grill-me C1）.

        清空窗口/基线/归因计数/强制头部标志；保留 _fail_alerted（防刷屏，跨重置有效）。
        """
        try:
            self._reset_window()
            self._anchor_move_runs = 0
            self._baselines = {}
            self._gate_drift_count = 0
            self._force_head_keep = False
            self._gate_note_pending = False
            if reason:
                logger.info("cache_health 重置: %s", reason)
        except Exception:  # noqa: BLE001 — fail-open
            logger.debug("cache_health reset 异常（fail-open）", exc_info=True)

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
            "anchor_moved_in_win": self._anchor_moved_in_win,
            "anchor_moved_since_record": self._anchor_moved_since_record,
            "force_head_keep": self._force_head_keep,
            "fail_alerted": self._fail_alerted,
            "recovery_timeout_runs": self._recovery_timeout_runs,
            "gate_drift_count": self._gate_drift_count,
            "gate_note_pending": self._gate_note_pending,
            "baselines": dict(self._baselines),
        }
