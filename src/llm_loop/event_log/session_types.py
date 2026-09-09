"""会话域纯类型层（R9-P3-02 环②断裂：类型先行落位）.

自 core/session.py（SessionIdConflictError）与 event_log/fork.py（ForkReport）
逐字节抽出的零逻辑类型 + 新增 BranchSeed 种子 DTO。运行时零 llm_loop 依赖
（仅 stdlib + TYPE_CHECKING 标注）——session/fork 指向本模块均为单向边，
双侧 re-export 保持历史导入路径兼容（spec §5.4.3-1 同一对象语义）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # 仅类型标注，运行时零依赖（Tarjan 静态图不计）
    from llm_loop.core.message import Message
    from llm_loop.core.session import Session


class SessionIdConflictError(RuntimeError):
    """session_id 已由另一个workspace持有；全局Event/Archive键禁止复用。"""


@dataclass
class ForkReport:
    """fork 操作报告（design.md §2.2.2-A）.

    P1-6(2026-08-15，审计发现 #15)：fork 点落在 assistant(tool_calls) 与其 tool
    回执之间时，自动向前对齐到完整工具轮边界（不产孤儿声明——孤儿声明会在分支
    下次运行时被配对修复伪造 `[程序异常]` 回执）。``snapped_fork_point`` 为实际
    生效点（未指定 fork 点时为 None）。
    """

    new_session_id: str
    source_session_id: str
    fork_point: int | None
    inherited_event_count: int
    elapsed_ms: float
    success: bool
    error: str = ""
    snapped_fork_point: int | None = None  # 工具轮边界对齐后的实际 fork 点（如实）


@dataclass(frozen=True)
class BranchSeed:
    """分支会话种子（R9-P3-03：fork 数据生成 ↔ SessionStore 重建的分界 DTO）.

    全部为字段值快照（fork 内完成求值——created_at/title 求值时点等价）；
    SessionStore.create_branch(seed) 只做"从 seed 构造 Session + save"，
    零逻辑加工（纯 move 语义，design T4-C 切分线）。
    """

    new_session_id: str
    messages_prefix: list[Message]  # fork 侧 list(prefix) 快照
    created_at: str  # fork 内 _now_iso() 求值结果
    title: str  # fork 内 (source.title or "未命名") + "（分支）" 求值结果
    parent_id: str
    branch_id: str
    branch_summary: str
    channel: str


class BranchWriter(Protocol):
    """fork 侧对 session 持久层的窄口协议（D4 依赖倒置——design §2.2.2）.

    fork 只感知本协议三方法（实测使用面：load 源会话 :79 / claim 唯一 id :126 /
    create_branch 重建 :145），不感知完整 SessionStore（结构耦合最小化）；
    SessionStore 结构性满足。Protocol 不参与运行时——类型声明零行为变化。
    """

    def load(self, session_id: str) -> Session: ...

    def claim_session_id(self, session_id: str) -> None: ...

    def create_branch(self, seed: BranchSeed) -> Session: ...
