"""LoopEngine 工具执行职责 mixin（M53 拆分: engine.py 946 行→按职责分文件，纯重构行为零变化）.

move 自 engine.py 内联工具段（492-553）与辅助方法（888-913）及模块级函数（49-67）：
- assistant 声明配对（约束 C1）、缺 id 如实反馈
- 只读并行/修改串行/按声明顺序回写（EVO-20260810-750e985a）
- tool_round 进展外泄（P2-1，fail-open）与 tool_trace 记录
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# EVO-20260814-aab7eb0b P2: 循环实时停滞检测阈值
# 连续 N 次相同指纹（tool_name + 规范化参数 JSON）：
#   >= _STAGNATION_REMIND_AT 达阈值（事件留痕）；>= _STAGNATION_BREAK_AT 熔断如实结束。
# R8.24-B B-D3: [停滞提醒] prompt 注入已取消（总审计 §11.3 撤销判定）——计数/阈值/
# 熔断/BLOCKED 全保留；提醒改为事件观测（LFL_STAGNATION_REMINDER 三态控制事件粒度）。
_STAGNATION_REMIND_AT = 3
_STAGNATION_BREAK_AT = 5


def _stagnation_reminder_mode() -> str:
    """R8.24-B B-1.1: 提醒事件观测模式（三态，均零 prompt 注入）.

    - "on"（默认）: 达阈值记 "suppressed" 事件（观测在场）
    - "shadow":     达阈值记 "suppressed_shadow" 事件（shadow 观测期语义）
    - "off":        完全静默（仅计数/熔断机械路径）
    """
    raw = (os.environ.get("LFL_STAGNATION_REMINDER", "on") or "on").strip().lower()
    return raw if raw in {"on", "shadow", "off"} else "on"

# EVO-20260823-9bb27899: 搜索/定位类工具目标级停滞检测
# 背景: 原指纹 = 工具名 + 完整参数 JSON 全等匹配；"换深度/换目录/换工具搜同一目标"时
# 每次指纹都变 → 连续计数恒为 1 → 检测失效（实测 28 次搜索循环未被拦截）。
# 对策: ① 对搜索类工具提取"目标指纹"（同目标不同细节参数 → 同一指纹 → 计数累计）；
#       ② 搜索类工具连续空结果达阈值 → 注入 [搜索空结果提醒]（目标可能不存在/前提失效）。
_SEARCH_LIKE_TOOLS = {"search_files", "search_records", "search_archive", "search_docs"}
# 各搜索类工具用于判定"找什么"的核心字段（忽略 limit/root/offset 等细节参数）
_SEARCH_TARGET_FIELDS = {
    "search_files": ("pattern", "content"),
    "search_records": ("kind", "query"),
    "search_archive": ("query", "role", "tool_name"),
    "search_docs": ("query", "doc_type"),
}
_EMPTY_SEARCH_REMIND_AT = 2  # 连续空结果达此数 → 注入 [搜索空结果提醒]（一次）


def _is_search_like_command(command: str) -> bool:
    """execute_command 是否为定位/搜索类只读命令（find/grep/rg/locate/which 前缀）.

    边界①补全（EVO-20260823-12be9cac）: 上轮 28 次搜索循环里有大量 execute_command
    变体（find 换深度/换目录反复搜同一目标），其空结果同样应触发停滞提醒——否则
    "find/grep 空结果反复重试"这条腿没被斩断。严格限定只读定位类前缀，防误判
    （如 python 脚本正常无输出不视为搜索空结果）。
    """
    cmd = (command or "").strip().lstrip()
    return cmd.startswith(("find ", "grep ", "rg ", "locate ", "which "))


def _is_search_like_call(tc) -> bool:
    """判定一次工具调用是否属"定位/搜索类"（结构化搜索工具 或 execute_command 搜索命令）."""
    if tc.name in _SEARCH_LIKE_TOOLS:
        return True
    if tc.name == "execute_command":
        cmd = str((tc.arguments or {}).get("command", ""))
        return _is_search_like_command(cmd)
    return False


def _search_target_key(tc) -> str:
    """提取搜索类调用的"目标"登记键（用于否定帧，同目标跨工具/跨会话命中）."""
    args = tc.arguments or {}
    if tc.name == "execute_command":
        return f"cmd:{str(args.get('command', ''))[:200]}"
    if tc.name == "search_files":
        return f"pattern:{args.get('pattern') or args.get('content') or ''}"
    # search_records / search_archive / search_docs: 用 query 作目标
    return f"query:{args.get('query') or ''}"


def _is_empty_search_result(result) -> bool:
    """搜索类工具是否空结果（EVO-20260823-9bb27899: 前提失效信号）.

    宽松判定: 结果为空、或无匹配/未找到/空列表类标记（不依赖精确格式，fail-safe）。
    """
    if result is None:
        return False
    if result.status and result.status.value != "success":
        return False
    content = (result.content or "").strip()
    if not content:
        return True
    markers = ("未找到匹配", "无匹配", "未命中", "空列表", "未检索到匹配", "无输出")
    return any(m in content for m in markers)


def _json_dumps_args(arguments: dict) -> str:
    """工具参数序列化为 JSON 字符串（FC 协议 function.arguments 要求）."""
    import json as _json

    try:
        return _json.dumps(arguments, ensure_ascii=False)
    except TypeError:
        return "{}"


def _tool_args_summary(arguments: Any) -> str:
    """工具参数摘要（P2-1，design §2.5.1 B4）：JSON 序列化 + 超 200 字符截断附 "…"。"""
    import json as _json

    try:
        s = (
            _json.dumps(arguments, ensure_ascii=False)
            if isinstance(arguments, dict)
            else str(arguments)
        )
    except (TypeError, ValueError):
        s = str(arguments)
    return s[:200] + "…" if len(s) > 200 else s
