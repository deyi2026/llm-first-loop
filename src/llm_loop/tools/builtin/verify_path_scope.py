"""write scope 只读观测工具（DESIGN-20261030 §5.3 C9 / FR-11 / T14）.

父会话/子代理只读地回答三个问题：
1. 当前生效的写侧授权范围：模式 + pattern 集合（``current_write_scope`` 为
   ``None`` 即全量、未收紧）；
2. 本进程审计快照里的已写路径集合（``written_paths``）；
3. 越界写入尝试次数（``violation_count``）与逐条明细（path + reason）。

机械边界（程序所有，语义归模型）：
- 纯只读：不写任何文件、不改任何状态、不触碰 scope 本身；
- 只读两个事实源，均为并行交付的钉死契约（本工具只读消费，不造依赖）：
  * ``llm_loop.core.run_context.current_write_scope``（ContextVar，C4）
  * ``llm_loop.core.write_scope.write_scope_audit_snapshot() -> dict``，形态：
    ``{"written_paths": [str, ...], "violations": [{"path": str, "reason": str}, ...],
    "violation_count": int, "scope_unverified": [{"path": str, "reason": str}, ...],
    "scope_unverified_count": int}``
- 绝不读取/回显文件内容——只回路径与计数（NFR-3 / §5.5 纪律）；
- fail-closed 观测：运行时未部署（缺 ContextVar 或审计模块）→ 确定性
  FAILURE 并说明缺口，绝不把"看不见"伪报成"0 次越界"；
- ``WriteScope`` 对象内部形态以交付实现为准（``mode`` / ``paths`` /
  ``deny_paths`` / ``declared``），另保留 ``allow`` / ``deny`` / ``patterns``
  属性探测兜底；**按 mode 标注允许/排除语义**（返修 B）：allow 模式下
  ``paths`` 标为「允许写入路径（未命中即拒绝写）」，deny 模式下标为
  「排除路径（命中即拒；排除集之外均允许写）」，``deny_paths`` 标为
  「继承/叠加的排除路径」——同一属性名在两种 mode 下语义相反，按属性名
  裸列会把 deny 排除集误读成允许集；探测不到任何 pattern 属性时如实标注
  "未识别"，不猜、不造；
  ``declared=False`` 按交付语义归一为"未声明=继承"（等价全量）；
- 审计为本进程内视图：父进程看不到子进程的审计快照；当前活跃写者视图
  不在本工具范围（C10/P1，task_frontier 域）。
"""

from __future__ import annotations

import importlib
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

_MAX_PATTERNS = 20
_MAX_WRITTEN_PATHS = 50
_MAX_VIOLATIONS = 20
_MAX_UNVERIFIED = 20
_PATTERN_ATTRS = ("allow", "deny", "deny_paths", "paths", "patterns")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


class VerifyPathScopeTool:
    name = "verify_path_scope"
    description = (
        "只读观测当前会话的写侧授权执行面（write scope）：当前生效的写入范围"
        "（模式 + pattern 集合，或全量）、本进程审计快照中的已写路径集合、"
        "越界写入尝试次数与逐条明细（path + reason）、已放行但无法证明落在"
        "scope 内的未验证路径（scope_unverified）。"
        "何时用: 父会话或子代理想确认'我现在被允许写哪些路径'、'已经写了哪些路径'、"
        "'越界写入被拒了几次'；交付前自检写侧足迹。"
        "何时不用: 查询其他工具的行为；查别的会话/子进程的审计（审计是本进程内"
        "视图，父进程看不到子进程的审计快照）；读取文件内容（本工具只回路径与"
        "计数，绝不读取/回显文件内容）；当前活跃写者视图（属 task_frontier）。"
        "边界: 纯只读——不写任何文件、不改任何状态、不触碰 scope 本身；"
        "依赖未部署时确定性 FAILURE，绝不把'看不见'伪报成'0 次越界'。"
    )
    parameters: dict = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def execute(self, **kwargs) -> ToolResult:
        return self._run()

    def _run(self) -> ToolResult:
        run_context = importlib.import_module("llm_loop.core.run_context")
        scope_var = getattr(run_context, "current_write_scope", None)
        if scope_var is None:
            return self._fail(
                "write scope 运行时未部署：core/run_context 缺 current_write_scope"
                "（依赖未就绪，如实失败，不伪造观测）"
            )
        try:
            write_scope_mod = importlib.import_module("llm_loop.core.write_scope")
        except ImportError:
            write_scope_mod = None
        if write_scope_mod is None or not callable(
            getattr(write_scope_mod, "write_scope_audit_snapshot", None)
        ):
            return self._fail(
                "审计模块未就绪：core/write_scope.write_scope_audit_snapshot 不可用"
                "（依赖未交付，如实失败，不伪造观测）"
            )

        # get(None)：未设置时按"无约束"处理（C4 契约默认 None = 全量）。
        scope = scope_var.get(None)
        try:
            audit = write_scope_mod.write_scope_audit_snapshot()
        except Exception as exc:  # noqa: BLE001 - 快照失败须如实上报，不静默归零
            return self._fail(f"审计快照读取失败: {type(exc).__name__}: {exc}")
        if not isinstance(audit, dict):
            return self._fail(
                f"审计快照形态异常（期望 dict，收到 {type(audit).__name__}）"
            )

        lines = [
            "[verify_path_scope] write scope 只读观测"
            "（纯只读：不写文件、不改状态、不回显文件内容）"
        ]
        lines.extend(self._scope_lines(scope))
        lines.extend(self._audit_lines(audit))
        lines.append(
            "边界: 审计为本进程内视图（父进程看不到子进程审计）；"
            "当前活跃写者视图不在本工具范围（task_frontier 域）。"
        )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(lines),
            tool_call_id="",
            tool_name=self.name,
        )

    # 返修 B：同一属性名在不同 mode 下语义相反（``paths`` 在 allow=允许集、
    # 在 deny=排除集），按属性名裸列会把 deny 排除集误读成允许集——按 mode
    # 标注语义；旧属性名兜底（allow/deny）与未知属性（patterns）不猜 mode 语义。
    def _attr_label(self, attr: str, mode: Any) -> str:
        if attr == "paths":
            if mode == "deny":
                return "paths=排除路径（deny 集：命中即拒；排除集之外均允许写）"
            if mode == "allow":
                return "paths=允许写入路径（allow 集：未命中即拒绝写）"
            return "paths=pattern 集（mode 未识别，允许/排除语义未知）"
        if attr == "deny_paths":
            return "deny_paths=继承/叠加的排除路径（父链累积：命中即拒，优先于允许集）"
        if attr == "allow":
            return "allow=允许集（旧属性名兜底：未命中即拒绝写）"
        if attr == "deny":
            return "deny=排除集（旧属性名兜底：命中即拒）"
        return attr  # patterns 等未知属性：如实列名，不造语义

    def _empty_group_note(self, attr: str, mode: Any) -> str:
        if attr == "paths" and mode == "allow":
            return "（空）= 空允许集，只读：拒绝一切写"
        if attr == "paths" and mode == "deny":
            return "（空）= 空排除集，全量放行形态（parse 层已拒该声明；此对象为直接构造）"
        return "（空）"

    def _scope_lines(self, scope: Any) -> list[str]:
        # 交付语义对齐：declared=False 表示"键不存在=继承父"（等价 None），
        # core/write_scope 判定入口同样按未声明归一，观测面不得另造口径。
        if scope is not None and getattr(scope, "declared", True) is False:
            return [
                "当前生效 write scope: 全量（declared=False=未声明，按继承归一，等价 None）",
                "- pattern 列表: 无（未声明模式下无 pattern 约束）",
            ]
        if scope is None:
            return [
                "当前生效 write scope: 全量（current_write_scope=None，本会话写侧未收紧）",
                "- pattern 列表: 无（全量模式下无 pattern 约束）",
            ]
        lines = ["当前生效 write scope: 受限（非全量）"]
        mode = getattr(scope, "mode", None)
        lines.append(f"- 模式(mode): {mode if mode is not None else '未标注'}")
        groups: list[tuple[str, list[str]]] = []
        total = 0
        for attr in _PATTERN_ATTRS:
            raw = getattr(scope, attr, None)
            if isinstance(raw, (list, tuple)):
                values = [str(p) for p in raw]
                # 空组无信息量，跳过——但 paths 例外：allow 模式下空 paths
                # =只读（拒绝一切写）是**有意义的语义**，必须呈现并注明，
                # 否则会被误读为无 pattern 约束
                if values or attr == "paths":
                    groups.append((attr, values))
                    total += len(values)
        if not groups:
            lines.append(
                "- pattern 列表: 未识别（对象无 allow/deny/paths/patterns 属性；"
                f"repr={_truncate(repr(scope), 200)}）"
            )
            return lines
        shown = 0
        for attr, values in groups:
            if shown >= _MAX_PATTERNS:
                break
            take = values[: _MAX_PATTERNS - shown]
            body = ", ".join(take) if take else self._empty_group_note(attr, mode)
            note = f"（该组截断，共 {len(values)} 条）" if len(take) < len(values) else ""
            lines.append(
                f"- {self._attr_label(attr, mode)} ({len(values)} 条): {body}{note}"
            )
            shown += len(take)
        if total > _MAX_PATTERNS:
            lines.append(f"- （pattern 总数 {total} 条，仅显示前 {_MAX_PATTERNS} 条）")
        return lines

    def _audit_lines(self, audit: dict) -> list[str]:
        lines: list[str] = []
        written_raw = audit.get("written_paths")
        if isinstance(written_raw, (list, tuple)):
            written = [str(p) for p in written_raw]
            lines.append(f"已写路径集合: 共 {len(written)} 条")
            for path in written[:_MAX_WRITTEN_PATHS]:
                lines.append(f"- {path}")
            if len(written) > _MAX_WRITTEN_PATHS:
                lines.append(
                    f"- …（共 {len(written)} 条，仅显示前 {_MAX_WRITTEN_PATHS} 条）"
                )
        else:
            lines.append(
                "已写路径集合: 快照缺 written_paths 或形态异常"
                f"（收到 {type(written_raw).__name__}）"
            )

        violations_raw = audit.get("violations")
        count_raw = audit.get("violation_count")
        has_details = isinstance(violations_raw, (list, tuple))
        if isinstance(count_raw, bool) or not isinstance(count_raw, int):
            count = len(violations_raw) if has_details else None
            count_note = "（快照缺 violation_count，按明细长度派生）" if count is not None else "（快照缺 violation_count 且明细形态异常）"
        else:
            count = count_raw
            count_note = ""
        if count is None:
            lines.append("越界写入尝试: 无法确定（快照缺 violation_count 且 violations 形态异常）")
        else:
            lines.append(f"越界写入尝试: {count} 次{count_note}")
        if has_details:
            details = [v for v in violations_raw if isinstance(v, dict)]
            malformed = len(violations_raw) - len(details)
            for v in details[:_MAX_VIOLATIONS]:
                path = str(v.get("path", "?"))
                reason = str(v.get("reason", "?"))
                lines.append(f"- {path} — {reason}")
            if len(details) > _MAX_VIOLATIONS:
                lines.append(f"- …（明细共 {len(details)} 条，仅显示前 {_MAX_VIOLATIONS} 条）")
            if malformed:
                lines.append(f"- （另有 {malformed} 条明细形态异常，未展开）")
            if isinstance(count_raw, int) and not isinstance(count_raw, bool) and count_raw != len(details):
                lines.append(
                    f"- 注意: 快照计数 {count_raw} 与明细条数 {len(details)} 不一致，"
                    "以快照计数为准（明细可能已被上游截断）"
                )

        lines.extend(self._unverified_lines(audit))
        return lines

    def _unverified_lines(self, audit: dict) -> list[str]:
        """scope_unverified 段：已放行但闸无法证明落在 scope 内的路径（DESIGN §16）."""
        raw = audit.get("scope_unverified")
        count_raw = audit.get("scope_unverified_count")
        if not isinstance(raw, (list, tuple)):
            return [
                "未验证路径(scope_unverified): 快照缺 scope_unverified 字段"
                f"（收到 {type(raw).__name__}）"
            ]
        details = [v for v in raw if isinstance(v, dict)]
        if isinstance(count_raw, bool) or not isinstance(count_raw, int):
            count = len(details)
            count_note = "（快照缺 scope_unverified_count，按明细长度派生）"
        else:
            count = count_raw
            count_note = ""
        lines = [f"未验证路径(scope_unverified): {count} 条{count_note}"]
        for v in details[:_MAX_UNVERIFIED]:
            lines.append(f"- {str(v.get('path', '?'))} — {str(v.get('reason', '?'))}")
        if len(details) > _MAX_UNVERIFIED:
            lines.append(f"- …（明细共 {len(details)} 条，仅显示前 {_MAX_UNVERIFIED} 条）")
        return lines

    def _fail(self, content: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[verify_path_scope] {content}",
            tool_call_id="",
            tool_name=self.name,
        )
