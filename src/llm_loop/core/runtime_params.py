"""循环动态参数视图 RuntimeParams（design.md §5.2.1 / FR-AUTO-PARAM-01/02/03）.

修复 PARAM-01 核心缺口: adjust_strategy 的 ctx.strategy 写入 → 循环实际消费。

读取优先级: strategy（AI 调整，会话级动态值） > settings（静态默认，进程级）。
- 未调整参数返回 settings 默认值（P0/P1 零回归）
- 调整参数返回动态值，受白名单数值范围 + 全局 HARD_CAP 约束
- strategy 为 CorrectionContext.strategy 的引用（同一 dict，adjust_strategy 更新立即可见）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 全局硬上限（与既有 LLM_MAX_ITERATIONS 上限语义一致，防 AI 调参失控）
HARD_CAP_MAX_ITERATIONS = 500


@dataclass(frozen=True)
class ParamAdjustRecord:
    """参数调整记录（PARAM-05 审计，前值→后值）."""

    ts: str
    key: str
    before: Any
    after: Any
    session_id: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "key": self.key,
            "before": self.before,
            "after": self.after,
            "session_id": self.session_id,
        }


class RuntimeParams:
    """循环动态参数视图（动态优先、静态兜底）."""

    def __init__(self, settings: Any, strategy: dict | None = None) -> None:
        self._settings = settings
        self._strategy = strategy if strategy is not None else {}
        self._round_adjust_count = 0
        self._max_adjust_per_round = 3  # PARAM-03 频次预算（由 config 覆盖）
        self._history: list[ParamAdjustRecord] = []
        self._persist_path: Path | None = None
        self._session_id = ""

    # ── 配置注入（factory 装配）──
    def set_max_adjust_per_round(self, n: int) -> None:
        self._max_adjust_per_round = max(1, int(n))

    def set_persist_path(self, path: str | Path | None) -> None:
        self._persist_path = Path(path) if path else None

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id

    # ── 读取（动态优先、静态兜底）──
    def get(self, key: str, default: Any = None) -> Any:
        """读取参数：strategy 动态值优先（通过范围校验），否则 settings/default 兜底."""
        if key in self._strategy:
            dynamic = self._strategy[key]
            if self._valid(key, dynamic):
                return dynamic
        return default

    @property
    def max_iterations(self) -> int:
        default = self._settings.max_iterations
        val = self.get("max_iterations", default)
        # 全局硬上限约束
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return int(min(val, HARD_CAP_MAX_ITERATIONS))
        return default

    @property
    def history_max_chars(self) -> int:
        default = self._settings.history_max_chars
        return int(self.get("history_budget", default))

    @property
    def llm_timeout_s(self) -> float:
        default = self._settings.llm_timeout_s
        return float(self.get("timeout_s", default))

    @property
    def memory_top_k(self) -> int:
        """记忆检索条数（M57 配置面收敛：AI 经 adjust_strategy 可调，动态优先）."""
        default = getattr(self._settings, "memory_top_k", 5)
        return int(self.get("memory_top_k", default))

    @property
    def extract_interval_msgs(self) -> int:
        """会话状态快照注入间隔（M58 配置面收敛：AI 经 adjust_strategy 可调，动态优先）."""
        default = getattr(self._settings, "extract_interval_msgs", 20)
        return int(self.get("extract_interval_msgs", default))

    @property
    def retrieve_semantic_top_k(self) -> int:
        """语义检索召回上限（M59 配置面收敛：AI 经 adjust_strategy 可调，动态优先）."""
        default = getattr(self._settings, "retrieve_semantic_top_k", 20)
        return int(self.get("retrieve_semantic_top_k", default))

    # ── 白名单范围校验（与 strategy_whitelist 一致）──
    def _valid(self, key: str, val: Any) -> bool:
        ranges = {
            "max_iterations": (5, HARD_CAP_MAX_ITERATIONS),
            "timeout_s": (5, 600),
            "history_budget": (1000, 1000000),
            "memory_top_k": (1, 50),
            "extract_interval_msgs": (5, 200),
            "retrieve_semantic_top_k": (1, 100),
        }
        r = ranges.get(key)
        if r is None:
            return False
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return r[0] <= val <= r[1]

    # ── 调整记录（adjust_strategy 调用的审计入口）──
    def record_adjust(self, key: str, before: Any, after: Any) -> None:
        """记录一次参数调整（PARAM-05）."""
        self._round_adjust_count += 1
        rec = ParamAdjustRecord(
            ts=datetime.now(UTC).isoformat(),
            key=key,
            before=before,
            after=after,
            session_id=self._session_id,
        )
        self._history.append(rec)
        self._persist(rec)

    def record_adjust_multi(self, proposed: dict) -> None:
        """批量记录一次策略调整（adjust_strategy 调用，PARAM-03/05）.

        记录前值→后值并落盘；每 key 计一次频次。
        """
        for key, after in proposed.items():
            before = self._strategy.get(key)
            self._round_adjust_count += 1
            rec = ParamAdjustRecord(
                ts=datetime.now(UTC).isoformat(),
                key=key,
                before=before,
                after=after,
                session_id=self._session_id,
            )
            self._history.append(rec)
            self._persist(rec)

    def can_adjust(self) -> bool:
        """本 run 内调整次数预算判定（PARAM-03）."""
        return self._round_adjust_count < self._max_adjust_per_round

    def adjust_count(self) -> int:
        return self._round_adjust_count

    def reset_round(self) -> None:
        """每轮循环重置频次计数."""
        self._round_adjust_count = 0

    def current(self) -> dict:
        """当前生效值快照（前值/后值对比、审计用；M57-M59 增策略参数）."""
        return {
            "max_iterations": self.max_iterations,
            "timeout_s": self.llm_timeout_s,
            "history_budget": self.history_max_chars,
            "memory_top_k": self.memory_top_k,
            "extract_interval_msgs": self.extract_interval_msgs,
            "retrieve_semantic_top_k": self.retrieve_semantic_top_k,
        }

    def reset(self, key: str | None = None) -> dict:
        """参数回滚（PARAM-06）: 恢复默认值（删除动态值），返回回滚后快照."""
        if key is not None:
            self._strategy.pop(key, None)
        else:
            self._strategy.clear()
        return self.current()

    # ── 持久化（审计可检索，DFX-MNT-05；M18 AA3: 参数调整不跨进程恢复，重启回默认）──
    def _persist(self, rec: ParamAdjustRecord) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persist_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            pass  # fail-open

    def load_history(self) -> list[dict]:
        """读取调整历史（可检索）."""
        if self._persist_path is None or not self._persist_path.exists():
            return []
        out: list[dict] = []
        try:
            with self._persist_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
        except (OSError, json.JSONDecodeError) as exc:  # fail-open：读调整历史失败返回已读部分
            logger.warning("读参数调整历史失败（fail-open），返回已读部分: %s", exc)
        return out
