"""基础工具: spawn_subagent 递归子代理（EVO 第五项，参考 OpenRSI 四算子 + 执行反馈）.

LLM 自主拆解复杂任务 → 启动非阻塞子代理（独立会话隔离 + 父执行域继承 + 真实执行）→
父代理继续决策，可中途 agent_message steer，并用 subagent_result 回收结果。
递归深度由 runner 控制（depth 参数自动自增，超限拒绝）。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.subagent.runner import child_spawn_grant_allowed


def _canary_zero_tool_parent() -> bool:
    """当前父会话是否为程序 pin 的 canary 直发（EVO-20261025-9ba80656）。

    canary dispatch 层把 spawn 参数 pin 为恰 {"tools": []}（零工具诊断
    child），该路径的空数组是程序构造、非模型笔误；除它之外，模型调用面的
    requires.tools=[] 一律在 spawn 时确定性拒绝。检测方式与 runner 侧
    canary 判定保持一致（budget grant profile）。
    """
    try:
        from llm_loop.resources import task_budget_subagent_profile as canary_profile
        from llm_loop.resources.task_budget_dispatch import active_task_budget

        parent_budget = active_task_budget()
        return (
            parent_budget is not None
            and parent_budget._get_validated()["grant"]["profile"] == canary_profile.PROFILE
        )
    except Exception:  # noqa: BLE001 — 预算面不可用时按普通调用处理（走拒绝路径）
        return False


# requires 形状错误文案（_parse_requirements 拒绝路径用；文本保持逐字节不变）。
_REQUIRES_SHAPE_ERROR = (
    "[参数错误] requires 需为对象 {tools?: [工具名], network?: bool, "
    "fs?: bool, fs_isolation?: bool, session_continuity?: bool, "
    "write_scope?: {paths: [pattern], mode?: 'allow'|'deny'}}"
)


def _parse_requirements(
    requires_raw: Any, tool_name: str
) -> tuple[Any, bool, ToolResult | None]:
    """解析 requires 声明并执行 write_scope fail-closed 守卫（execute 原内联逻辑原样搬迁）.

    DESIGN-20261030 §5.3 C2/§5.10 NFR-4: write_scope 声明必须被解析面真实
    承载——SurfaceRequirements.from_kwargs 不识别该键（依赖未就绪/跨版本
    旧端）时确定性拒绝，绝不静默忽略写侧授权声明（fail-closed）。
    形状错误（非 None 输入解析为 None）同样在此确定性拒绝，回执与历史逐字节一致。

    放在模块级 helper 而非 execute 内联：execute 的函数体行数受 R9 棘轮
    "只降不升"约束（tests/guards/function_size_baseline.json，登记 170），
    write_scope 解析/守卫的说明文本不得抬高该红线。
    """
    from llm_loop.core.execution_surface import SurfaceRequirements

    reqs = SurfaceRequirements.from_kwargs(requires_raw)
    if requires_raw is not None and reqs is None:
        return reqs, False, ToolResult(
            status=ToolResultStatus.FAILURE,
            content=_REQUIRES_SHAPE_ERROR,
            tool_call_id="",
            tool_name=tool_name,
        )
    declared = (
        reqs is not None
        and isinstance(requires_raw, dict)
        and "write_scope" in requires_raw
    )
    if declared and not hasattr(reqs, "write_scope"):
        return reqs, declared, ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                "[参数错误] requires.write_scope 声明未被当前解析面识别"
                "（执行面不支持该字段）；为不静默忽略写侧授权声明，child 未启动。"
            ),
            tool_call_id="",
            tool_name=tool_name,
        )
    return reqs, declared, None


def _required_write_scope_kwargs(reqs: Any, declared: bool) -> dict:
    """DESIGN-20261030 §5.3 C2: 仅在声明 write_scope 时携带该参数——
    既有调用的 kwargs 面与 runner 行为零变化。

    放在模块级 helper 而非 execute 内联：同 _parse_requirements 的 R9 棘轮约束。
    """
    return {"required_write_scope": reqs.write_scope} if declared else {}


class SpawnSubAgentTool:
    name = "spawn_subagent"
    # nonblocking start 只负责登记 handle + 启线程，不再同步等待 child。
    registry_timeout_s = 5.0
    description = (
        "非阻塞启动子代理并立即返回 child_id。何时用: 复杂任务需要拆解成独立子任务"
        "（如独立调研/独立计算/并行验证）时，让 child 在独立会话上下文中后台真实执行，"
        "父代理继续决策（默认隔离的是会话上下文，不含文件系统隔离）。"
        "何时不用: 任务简单直接处理时；子任务依赖父上下文大量状态时。"
        "启动成功后可用 agent_message(target_id=child_id, ...) 中途纠偏；"
        "用 subagent_result(child_id, wait_seconds=...) 查询/等待报告与最终结果。"
        "注意: 子代理继承父代理当前工具执行域（授权只降不升）；"
        "requires.fs_isolation=true 仅提供 best-effort 施工面隔离（独立 git worktree，"
        "非安全沙箱：execute_command 经绝对路径/跨目录操作仍可越界）。"
        "requires.tools 一旦声明即程序级强制白名单（EVO-20261012-bb3022f4）：child 的"
        "工具发现面与执行面都被截断到声明集，调用声明外工具由运行时确定性拒绝；"
        "声明超出父执行域时 spawn 直接拒绝。spawn_subagent 默认不在 child 工具面"
        "（防递归舰队；如需真正分层舰队需运维以 CHILD_SPAWN_GRANT 显式授予）。"
        "各工具自身安全/授权/并发写保护继续生效。"
        "递归深度由程序计算，上限 3，超限会拒绝。"
        "requires.network/fs/session_continuity 为能力需求声明，缺口在 child 启动前拒绝。"
        "spawn 成功只代表 child 已启动，不代表子任务完成；最终 outcome 以 subagent_result 为准。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "子任务描述（明确目标/约束/期望产出，越具体越好）",
            },
            "context": {
                "type": "string",
                "description": "父上下文要点（可选；子代理无需父全量历史，只传必要背景）",
            },
            "inherit": {
                "type": "boolean",
                "description": (
                    "fork 继承（可选，默认 false）：不自动注入父会话 turn；仅提供去除私有 "
                    "reasoning/provider replay 的 exact parent-context artifact ref，由 child 按需读取；"
                    "可与 context 并存。"
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "可选 provider/model。省略时机械继承当前父 run 的实际模型；填写时由现有"
                    "模型注册表校验/路由，程序不替模型选择厂家。"
                ),
            },
            "acceptance": {
                "type": "array",
                "items": {"type": "string"},
                "description": "验收清单（可选，对齐 dsh_task 协议 v2）：子代理完成时逐项自检输出"
                               "完成/未完成/原因——分歧显性化，父级保留最终裁决权。给验收标准后"
                               "子代理结果更可靠（自检倒逼收敛，避免'答非所问'）。",
            },
            "requires": {
                "type": "object",
                "properties": {
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "强制白名单（EVO-20261012-bb3022f4）：child 的工具面被程序截断到"
                            "该集合（只降不升，超出父执行域直接拒绝）；调用声明外工具由"
                            "运行时确定性拒绝。请把子任务真正需要的工具列全。"
                        ),
                    },
                    "network": {
                        "type": "boolean",
                        "description": "是否需要出站网络（web_fetch/web_search/execute_command 等）",
                    },
                    "fs": {
                        "type": "boolean",
                        "description": "是否需要工作区文件系统读写",
                    },
                    "fs_isolation": {
                        "type": "boolean",
                        "description": (
                            "git worktree 文件系统隔离（默认 false，EVO-20261016-ac47e850）："
                            "true 时 child 在 <workspace>/.worktrees/lfl-child-*/ 的独立 git "
                            "worktree 中施工，其 fs 工具面以隔离树为基准解析，与父工作区改动"
                            "互不干扰（best-effort 施工面隔离：execute_command 经绝对路径/"
                            "跨目录操作仍可越界，非安全沙箱，不可用于约束不可信代码）。"
                            "父工作区须为 git 仓库且磁盘充足，否则 spawn 带 reason_code 拒绝"
                            "（不降级共享工作区）。终态不自动合并：脏树保留并在结果中报告路径"
                            "与 HEAD，合并回父是父会话的显式动作。"
                        ),
                    },
                    "session_continuity": {
                        "type": "boolean",
                        "description": "是否需要 terminal 后可续话（本执行面支持，声明用于 fail-fast）",
                    },
                    "write_scope": {
                        "type": "object",
                        "properties": {
                            "paths": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "可写路径 pattern（glob，相对当前工作区根；"
                                    "显式空数组 = 只读 child）"
                                ),
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["allow", "deny"],
                                "description": (
                                    "allow=按 paths 放行（默认）；deny=在父 scope "
                                    "内按 paths 排除"
                                ),
                            },
                        },
                        "additionalProperties": False,
                        "description": (
                            "写侧路径归属声明（DESIGN-20261030 §5.2）：与父 write "
                            "scope 程序级求交（只降不升），声明超出父 scope 时 spawn "
                            "直接拒绝（fail-fast，不静默截断）；不声明则继承父 "
                            "scope（父为全量时子为全量）。它是写侧护栏而非安全沙箱："
                            "execute_command 等通道的越界仍由各工具自身安全面约束。"
                        ),
                    },
                },
                "description": (
                    "能力需求显式声明（可选，EVO-20260914-1eb26afa + EVO-20261012-bb3022f4）："
                    "tools=强制白名单（child 工具面截断到声明集，程序级拦截）；"
                    "network/fs/session_continuity 在 child 启动前比对执行面能力矩阵，"
                    "缺口即在启动前拒绝并给出替代执行面提示（只提前'必然失败'，"
                    "不放宽任何授权边界）。fs_isolation=true 额外将 child 施工面切到独立 git "
                    "worktree（EVO-20261016-ac47e850；best-effort 施工面隔离，非安全沙箱："
                    "child 的 execute_command 经绝对路径/跨目录操作仍可越界，不可用于约束"
                    "不可信代码）。write_scope=写侧路径归属声明（DESIGN-20261030 "
                    "§5.2：与父 write scope 求交，只降不升，越界拒绝，不静默截断；"
                    "不声明则继承父 scope）。不声明则 child 继承父执行域"
                    "（spawn_subagent 除外，默认防递归）。"
                ),
            },
        },
        "required": ["task"],
    }

    def __init__(self, runner) -> None:
        self._runner = runner

    def terminate_session(self, session_id: str, *, run_generation: str = "") -> None:
        """父会话 Stop 向正在运行的 child/descendants 传播取消。"""
        self._runner.cancel_parent(session_id, run_generation=run_generation)

    def execute(self, **kwargs) -> ToolResult:
        task = str(kwargs.get("task", "")).strip()
        context = str(kwargs.get("context", "")).strip()
        inherit = bool(kwargs.get("inherit", False))
        # depth 属程序控制面：顶层 parent→0，子代理内再次 spawn→当前真实 depth+1。
        # 历史/模型即使携带 depth 参数也明确忽略，不能由模型绕过 max_depth。
        from llm_loop.subagent.runner import next_subagent_depth

        depth = next_subagent_depth()
        from llm_loop.tools.arg_coerce import coerce_str_list
        acceptance = coerce_str_list(kwargs.get("acceptance"))
        model = str(kwargs.get("model", "") or "").strip()

        if not task:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'task'（子任务描述）",
                tool_call_id="",
                tool_name=self.name,
            )

        # EVO-20260914-1eb26afa: 显式能力需求声明 → child 启动前矩阵比对早失败。
        # 不声明则不比对（零回归）；拒绝只针对"必然失败"的显式缺口。
        from llm_loop.core.execution_surface import (
            alternatives_hint,
            codearts_capability,
            local_subagent_capability,
            validate_requirements,
        )

        requires_raw = kwargs.get("requires")
        reqs, write_scope_declared, requires_reject = _parse_requirements(
            requires_raw, self.name
        )
        if requires_reject is not None:
            return requires_reject
        # EVO-20261025-9ba80656: requires.tools=[]（或全空白项）历史上被静默当作
        # "零工具强制白名单"传给 runner——child 启动后才发现任何工具都调不了，
        # 浪费整轮子会话 token 才暴露。现改为 spawn 时确定性拒绝并给出正确写法；
        # 唯一豁免：程序 pin 的 canary 直发零工具诊断 child（其 dispatch 层强制
        # requires 恰为 {"tools": []}，见 task_budget_subagent_profile）。
        if (
            reqs is not None
            and isinstance(requires_raw, dict)
            and "tools" in requires_raw
            and not [t for t in (reqs.tools or []) if str(t).strip()]
            and not _canary_zero_tool_parent()
        ):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[参数错误] requires.tools 为空数组（或全空白项）：这会把 child "
                    "工具面强制截断到空集（任何工具都不可用），几乎必然是笔误，child 未启动。"
                    "正确写法：继承父域请整个省略 requires 或省略 tools 键；显式白名单请列全"
                    "所需工具名（至少一个非空项）。零工具纯推理 child 仅程序内部 canary "
                    "路径使用，模型调用面不开放。"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        if reqs is not None and reqs.declared():
            # EVO-20261012-bb3022f4 (E4): 矩阵比对基准 = child 实际可见面 =
            # 父有效 scope（父 None = 全量 registry），未授予时先剔除 spawn_subagent
            # （child 面默认禁递归 spawn，防声明出永远不可用的工具）。
            try:
                from llm_loop.core.run_context import current_tool_discovery_scope

                _parent_scope = current_tool_discovery_scope.get()
                if _parent_scope is not None:
                    allowed_names = sorted(_parent_scope)
                else:
                    allowed_names = list(self._runner.registry.names())
                if not child_spawn_grant_allowed():
                    allowed_names = [n for n in allowed_names if n != "spawn_subagent"]
            except Exception:  # noqa: BLE001 — 矩阵派生失败不拦截既有行为
                allowed_names = None
            caps = local_subagent_capability(allowed_names)
            gaps = validate_requirements(caps, reqs)
            if gaps:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=(
                        "[状态: failure] 能力需求声明与执行面矩阵存在缺口，child 未启动:\n- "
                        + "\n- ".join(gaps)
                        + "\n"
                        + alternatives_hint(
                            reqs,
                            {
                                "local_subagent": caps,
                                "codearts": codearts_capability(),
                            },
                        )
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )

        try:
            # E4 (EVO-20261012-bb3022f4): 声明的 requires.tools 作为强制白名单
            # 传入 runner——child 的发现面与执行面都被程序截断到该集合。
            started = self._runner.start(
                task=task,
                context=context,
                depth=depth,
                inherit=inherit,
                acceptance=acceptance,
                model=model,
                required_tools=(
                    list(reqs.tools)
                    if reqs is not None
                    and isinstance(requires_raw, dict)
                    and "tools" in requires_raw
                    else None
                ),
                fs_isolation=bool(reqs.fs_isolation) if reqs is not None else False,
                **_required_write_scope_kwargs(reqs, write_scope_declared),
            )
        except Exception as exc:  # noqa: BLE001 — 子代理异常如实回传
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[状态: error] 子代理执行异常: {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
            )

        if not bool(started.get("accepted")):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[状态: failure] child_state={started.get('state', 'failed')} "
                    f"depth={started.get('depth', depth)} {started.get('detail', '')}"
                ).strip(),
                tool_call_id="",
                tool_name=self.name,
            )

        child_id = str(started.get("child_id", ""))
        tool_scope = str(started.get("tool_scope", "") or "")
        worktree = str(started.get("worktree", "") or "")
        parts = [
            f"[状态: success] child_state=running child_id={child_id} "
            f"depth={started.get('depth', depth)} model={started.get('model', '') or 'legacy_default'}",
            (
                f"tool_scope={tool_scope}（E4 强制白名单：声明外调用将被运行时确定性拒绝）"
                if tool_scope
                else ""
            ),
            (
                f"worktree={worktree}（声明式 git worktree 施工面隔离，best-effort、"
                "非安全沙箱：execute_command 经绝对路径/跨目录操作仍可越界；"
                "终态不自动合并，合并是父会话显式动作）"
                if worktree
                else ""
            ),
            "子代理已在后台启动；本回执不是任务结算。",
            f"中途纠偏: agent_message(target_id='{child_id}', content='...')",
            f"查询/等待: subagent_result(child_id='{child_id}', wait_seconds=0..30)",
        ]
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(parts),
            tool_call_id="",
            tool_name=self.name,
        )
