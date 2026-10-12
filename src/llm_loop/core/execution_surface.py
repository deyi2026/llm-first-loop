"""机器可读执行面能力矩阵 + spawn 前能力需求校验（EVO-20260914-1eb26afa 已批准）.

设计约束（EVO 原文约束，勿违背）:
1. 矩阵描述执行面真实能力，不放宽任何授权边界——校验失败只提前"必然失败"，
   校验通过不代表运行期必然成功（网络/配额/远端状态仍由各工具自身安全面裁决）。
2. 程序只做显式声明比对，不解析任务文本做语义推断（程序不做 AI 的判断）。
3. local_subagent 的允许工具集从 live 注册表演生（父执行域继承），避免静态清单漂移；
   codearts 为远端定义面，不可本地枚举，如实标注。

变更记录: 2026-09-14 EVO-20260914-1eb26afa（人工已批准）
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# 工具面能力分类（随工具注册表演进需同步维护的唯一定义点）:
# - 出站网络能力工具
EGRESS_TOOLS: frozenset[str] = frozenset(
    {"web_fetch", "web_search", "execute_command"}
)
# - 工作区文件系统读写工具
FS_TOOLS: frozenset[str] = frozenset(
    {"read_file", "edit_file", "search_files", "inspect_code", "read_image",
     "source_synopsis"}
)

SURFACE_LOCAL_SUBAGENT = "local_subagent"
SURFACE_CODEARTS = "codearts"


@dataclass(frozen=True)
class SurfaceCapability:
    """一个执行面的机器可读能力矩阵行."""

    surface: str
    # local_subagent: live 注册表派生的允许工具元组（父执行域继承后）；
    # codearts: None（远端定义，本地不可枚举）
    allowed_tools: tuple[str, ...] | None
    tool_enumeration: str  # "registry" | "remote_defined"
    network_egress: bool
    filesystem_scope: str  # "workspace" | "none" | "remote_sandbox"
    session_continuity: bool  # 是否支持 terminal 后有界续话（EVO-e6b8aa22）
    timeout_s_cap: int | None = None
    context_tokens_cap: int | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "allowed_tools": list(self.allowed_tools) if self.allowed_tools is not None else None,
            "tool_enumeration": self.tool_enumeration,
            "network_egress": self.network_egress,
            "filesystem_scope": self.filesystem_scope,
            "session_continuity": self.session_continuity,
            "timeout_s_cap": self.timeout_s_cap,
            "context_tokens_cap": self.context_tokens_cap,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class SurfaceRequirements:
    """spawn/step 显式声明的能力需求（模型填写，程序比对）.

    只校验显式声明项；未声明即不比对（零回归：不传 requires 的既有调用不受影响）。
    """

    tools: tuple[str, ...] = ()
    network: bool = False
    fs: bool = False
    session_continuity: bool = False

    @classmethod
    def from_kwargs(cls, raw: Any) -> SurfaceRequirements | None:
        """解析工具参数里的 requires 声明；非法结构返回 None（调用方回参数错误）."""
        if raw is None:
            return None
        if not isinstance(raw, dict):
            return None
        tools_raw = raw.get("tools")
        if tools_raw is None:
            tools: tuple[str, ...] = ()
        elif isinstance(tools_raw, str):
            tools = tuple(t.strip() for t in tools_raw.split(",") if t.strip())
        elif isinstance(tools_raw, (list, tuple)):
            tools = tuple(str(t).strip() for t in tools_raw if str(t).strip())
        else:
            return None
        if len(tools) > 64:  # 防滥用上限（声明超长即视为非法）
            return None
        return cls(
            tools=tools,
            network=bool(raw.get("network", False)),
            fs=bool(raw.get("fs", False)),
            session_continuity=bool(raw.get("session_continuity", False)),
        )

    def declared(self) -> bool:
        return bool(self.tools or self.network or self.fs or self.session_continuity)


def local_subagent_capability(
    allowed_tool_names: Iterable[str] | None,
    *,
    timeout_s_cap: int | None = None,
    context_tokens_cap: int | None = None,
) -> SurfaceCapability:
    """local_subagent 执行面矩阵：从 live 允许工具名派生网络/文件系统能力.

    allowed_tool_names=None 表示无法枚举（如装配早期）；此时 network/fs 如实
    标 False 且 notes 说明，由调用方决定是否放行（保守路径不应凭空拒绝既有行为）。
    """
    allowed = tuple(sorted(set(allowed_tool_names))) if allowed_tool_names is not None else ()
    enumerable = allowed_tool_names is not None
    names = frozenset(allowed)
    has_egress = enumerable and bool(names & EGRESS_TOOLS)
    has_fs = enumerable and bool(names & FS_TOOLS)
    return SurfaceCapability(
        surface=SURFACE_LOCAL_SUBAGENT,
        allowed_tools=allowed if enumerable else None,
        tool_enumeration="registry" if enumerable else "unavailable",
        network_egress=has_egress,
        filesystem_scope="workspace" if has_fs else ("none" if enumerable else "unknown"),
        session_continuity=True,  # EVO-e6b8aa22: terminal 后有界续话窗口
        timeout_s_cap=timeout_s_cap,
        context_tokens_cap=context_tokens_cap,
        notes=(
            "允许工具集=父执行域继承（live 派生）；工具自身安全/授权边界继续生效"
            if enumerable
            else "工具面暂不可枚举（装配早期），网络/文件系统能力未断言"
        ),
    )


def codearts_capability() -> SurfaceCapability:
    """codearts 远端执行面矩阵：能力由远端定义，本地不可枚举，如实标注."""
    return SurfaceCapability(
        surface=SURFACE_CODEARTS,
        allowed_tools=None,
        tool_enumeration="remote_defined",
        network_egress=True,
        filesystem_scope="remote_sandbox",
        session_continuity=False,
        notes=(
            "远端代理执行面：工具/文件系统由远端定义，本地不可枚举不猜；"
            "无本地会话连续性——跨 step 状态需经 context/ctx_path 显式传递"
        ),
    )


def validate_requirements(caps: SurfaceCapability, reqs: SurfaceRequirements) -> list[str]:
    """显式声明需求 vs 执行面矩阵 → 缺口列表（空=通过）.

    原则: 只对"显式声明"且"矩阵可断言"的维度拒绝；矩阵不可断言
    （remote_defined/unavailable）时给出如实提示而非臆断拒绝。
    """
    gaps: list[str] = []
    for tool in reqs.tools:
        if caps.allowed_tools is None:
            if caps.tool_enumeration == "remote_defined":
                gaps.append(
                    f"required tool '{tool}': 执行面 {caps.surface} 为远端定义面，"
                    f"无法本地断言该工具存在（不能凭空放行也不能臆断拒绝，请改用可枚举执行面或去远端确认）"
                )
            else:
                gaps.append(
                    f"required tool '{tool}': 执行面 {caps.surface} 工具面暂不可枚举，无法断言"
                )
        elif tool not in caps.allowed_tools:
            gaps.append(
                f"required tool '{tool}': 不在执行面 {caps.surface} 允许工具集内"
            )
    if reqs.network and not caps.network_egress:
        gaps.append(
            f"required network egress: 执行面 {caps.surface} 无出站网络工具"
        )
    if reqs.fs and caps.filesystem_scope == "none":
        gaps.append(
            f"required filesystem: 执行面 {caps.surface} 无工作区文件系统工具"
        )
    if reqs.session_continuity and not caps.session_continuity:
        gaps.append(
            f"required session continuity: 执行面 {caps.surface} 不支持 terminal 后续话"
            f"（跨轮状态请经 context/ctx_path 显式传递）"
        )
    return gaps


def alternatives_hint(
    reqs: SurfaceRequirements,
    surfaces: dict[str, SurfaceCapability],
) -> str:
    """给出满足声明的其他执行面提示（仅基于矩阵事实）."""
    ok = [
        sid
        for sid, caps in surfaces.items()
        if not validate_requirements(caps, reqs)
    ]
    if not ok:
        return "当前注册执行面均无法满足该声明需求"
    return "满足该声明需求的执行面: " + ", ".join(sorted(ok))


EXECUTION_SURFACE_MATRIX_DOC = (
    "执行面能力矩阵（EVO-20260914-1eb26afa）: spawn/step 可用 requires 显式声明"
    "能力需求(tools/network/fs/session_continuity)，程序在 child 启动前比对矩阵，"
    "缺口即拒绝并给出替代执行面提示；只提前'必然失败'，不放宽任何授权边界。"
    "local_subagent 允许工具集随父执行域动态派生；codearts 为远端定义面。"
)
