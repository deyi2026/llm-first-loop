"""Kernel 侧只读补偿记录读取器（M2-2 runtime→feishu 架构边偿还）.

契约 docs/ARCHITECTURE-20261007-kernel-v1-contract.md §3/§5：runtime（kernel）
不得 import ``llm_loop.feishu``（capability），也不得用函数内隐藏导入规避
AST guard。原先 service_control 借函数内 import 调用的「只读 compensation
记录解析」事实整体下沉到本模块（仅标准库依赖）；capability 侧
``llm_loop.feishu.compensation`` 从这里 import 并包装为自己的 dataclass
（capability→kernel 方向，契约允许），公共 API 与行为保持不变。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 结构化中断原因五类（FTR-DFX-08：禁止脆弱文本匹配分类）。单一事实源在此
# （kernel），llm_loop.feishu.compensation 从此 re-export 保持公共 API 不变。
WATCHDOG_EXIT = "watchdog_exit"
QUEUE_FULL = "queue_full"
DRAIN_TIMEOUT = "drain_timeout"
PROCESS_TIMEOUT = "process_timeout"
CRASH = "crash"
INTERRUPT_CAUSES: tuple[str, ...] = (
    WATCHDOG_EXIT,
    QUEUE_FULL,
    DRAIN_TIMEOUT,
    PROCESS_TIMEOUT,
    CRASH,
)

REPLY_TYPES = frozenset({"chat_id", "open_id"})

_COMPENSATION_PATH_ENV = "FEISHU_COMPENSATION_PATH"
_DEFAULT_COMPENSATION_PATH = "data/feishu_compensation.jsonl"
_LEGACY_INTERRUPTED_PATH_ENV = "FEISHU_INTERRUPTED_PATH"
_DEFAULT_LEGACY_INTERRUPTED_PATH = "data/feishu_interrupted.json"


def compensation_path() -> str:
    """补偿记录 JSONL 路径（默认 data/feishu_compensation.jsonl，可经 env 配置）."""
    return os.environ.get(_COMPENSATION_PATH_ENV, "") or _DEFAULT_COMPENSATION_PATH


def legacy_interrupted_path() -> str:
    """旧单文件补偿路径（默认 data/feishu_interrupted.json，启动迁移数据源）."""
    return os.environ.get(_LEGACY_INTERRUPTED_PATH_ENV, "") or _DEFAULT_LEGACY_INTERRUPTED_PATH


def _resolve_runtime_path(configured: str, runtime_root: str | Path | None) -> Path | None:
    """把 env 可配的（可能相对的）补偿路径解析为绝对 Path（M2-2）.

    bridge 进程的 cwd 即 runtime_root，因此相对路径的运行时语义 = runtime_root
    下解析；runtime_root 缺失时相对路径不可解析 → None（fail-closed，调用方按
    证据不足处理）。绝对路径配置不受 runtime_root 影响。
    """
    path = Path(configured)
    if path.is_absolute():
        return path
    if runtime_root is None:
        return None
    return Path(runtime_root) / path


@dataclass(kw_only=True, frozen=True)
class CompensationRecordData:
    """Kernel 中立补偿记录只读 DTO（capability 层包装为 InterruptionCompensationRecord）."""

    receive_id: str  # 补偿回复目标会话（chat_id / open_id）
    reply_type: str  # "chat_id" | "open_id"
    interrupt_cause: str  # 五类结构化原因（FTR-DFX-08）
    interrupted_at: str  # 中断时点（ISO8601；只读路径必填非空）
    context_ref: str = ""  # 上下文引用（可空；非 str 一律归 ""，与既有解析一致）
    msg_id: str = ""  # 被打断消息 id（可空）


def _validate_record_values(*, receive_id: str, reply_type: str, interrupt_cause: str) -> None:
    """取值合法性校验（InterruptionCompensationRecord.__post_init__ 的 kernel 侧等价复刻）.

    原只读链路把非法值交给 Feishu dataclass 构造器 raise → 外层 except →
    整体 None（fail-closed）。本模块不依赖 Feishu dataclass，故在此逐条
    复刻同序校验（receive_id 非空 → reply_type 枚举 → cause 枚举），保持
    「任一非法值 = 整体不可读」的原行为。
    """
    if not receive_id:
        raise ValueError("receive_id 必填非空（补偿回复目标会话）")
    if reply_type not in REPLY_TYPES:
        raise ValueError(f"reply_type 非法: {reply_type!r}（仅 chat_id/open_id）")
    if interrupt_cause not in INTERRUPT_CAUSES:
        raise ValueError(f"interrupt_cause 非法: {interrupt_cause!r}")


def read_compensation_records(
    runtime_root: str | Path | None = None,
) -> list[CompensationRecordData] | None:
    """纯只读补偿记录读取（M2-2；供 service_control 空闲判定，零写副作用）.

    与 ``CompensationStore.read_all`` 的关键差异：绝不调用 ``_ensure_migrated()``
    （迁移会改写 JSONL 并删除 legacy 单文件——只读判定不得有写副作用）；
    解析策略相反：单行损坏在 read_all 是跳过隔离，本函数整体失败返回 None
    （fail-closed：无法排除目标 msg_id 恰在损坏行中，"跳过"会把证据不足
    误判为无补偿）。

    Args:
        runtime_root: 桥运行根目录（相对路径解析基准，与 bridge cwd=runtime_root
            语义一致）；绝对路径配置不受影响；相对路径且 runtime_root=None → None。

    Returns:
        解析成功：记录列表（JSONL 与 legacy 均缺失/空 = []，不创建任何文件）；
        读取/解析失败：None（调用方必须按证据不足处理，不得视作"无补偿"）。
    """
    records: list[CompensationRecordData] = []
    jsonl = _resolve_runtime_path(compensation_path(), runtime_root)
    if jsonl is None:
        return None
    try:
        if jsonl.exists():
            for line_no, raw in enumerate(jsonl.read_text(encoding="utf-8").splitlines(), 1):
                line = raw.strip()
                if not line:
                    continue
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError(f"补偿行非对象（{jsonl}:{line_no}）")
                # M2-2 P1-B fail-closed：五个字段必须显式存在且为字符串——
                # 缺失/非字符串一律整行无效（外层 fail-closed None → busy），
                # 绝不默认补 chat_id/CRASH 制造"记录合法"的假象。取值合法性
                # （reply_type/cause 枚举）由 _validate_record_values 复刻
                # dataclass 校验。legacy 单文件兼容路径保留既有默认（历史
                # 格式无 cause，按 CRASH）。
                for field_name in (
                    "receive_id",
                    "reply_type",
                    "interrupt_cause",
                    "interrupted_at",
                    "msg_id",
                ):
                    value = data.get(field_name)
                    if not isinstance(value, str):
                        raise ValueError(
                            f"字段缺失或非字符串: {field_name}={value!r}（{jsonl}:{line_no}）"
                        )
                if not data["interrupted_at"]:
                    # 不允许记录构造器自动补时点（dataclass 空时点会填 now）：
                    # 存储侧缺时点 = 记录无效（矩阵 D empty_ts 反例）
                    raise ValueError(f"interrupted_at 为空（{jsonl}:{line_no}）")
                _validate_record_values(
                    receive_id=data["receive_id"],
                    reply_type=data["reply_type"],
                    interrupt_cause=data["interrupt_cause"],
                )
                context_ref_raw = data.get("context_ref")
                records.append(
                    CompensationRecordData(
                        receive_id=data["receive_id"],
                        reply_type=data["reply_type"],
                        interrupt_cause=data["interrupt_cause"],
                        interrupted_at=data["interrupted_at"],
                        context_ref=(context_ref_raw if isinstance(context_ref_raw, str) else ""),
                        msg_id=data["msg_id"],
                    )
                )
    except (OSError, ValueError) as exc:  # JSONDecodeError ⊂ ValueError，整体 fail-closed
        logger.warning("补偿 JSONL 只读解析失败（fail-closed，按证据不足处理）: %s", exc)
        return None
    legacy = _resolve_runtime_path(legacy_interrupted_path(), runtime_root)
    if legacy is None:
        return None
    try:
        if legacy.exists():
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"legacy 补偿非对象: {legacy}")
            if not str(data.get("interrupted_at", "")):
                raise ValueError(f"legacy interrupted_at 缺失: {legacy}")
            receive_id = str(data.get("reply_id", ""))
            reply_type = str(data.get("reply_type", "chat_id") or "chat_id")
            _validate_record_values(
                receive_id=receive_id, reply_type=reply_type, interrupt_cause=CRASH
            )
            records.append(
                CompensationRecordData(
                    receive_id=receive_id,
                    reply_type=reply_type,
                    interrupt_cause=CRASH,
                    interrupted_at=str(data.get("interrupted_at", "")),
                    msg_id=str(data.get("msg_id", "")),
                )
            )
    except (OSError, ValueError) as exc:
        logger.warning("legacy 补偿只读解析失败（fail-closed，按证据不足处理）: %s", exc)
        return None
    return records
