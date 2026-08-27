"""任务聚焦模块（2026-08-22 独立，用户决策）.

把"任务聚焦"关注点从核心循环（engine/build/routing）抽出独立成模块——
切换锁定、注入包装、任务锚点、简单任务判定四个职责集中一处，可独立测试。

背景（实证 98605ad7）: 48 次工具调用一半是重复探测, 68 分钟未完成任务——
本地模型被注入消息（切换感知/记忆/经验/提醒）误读为"独立消息/新任务"而绕路;
复杂任务被误判简单切到 9B 快模型导致漂移; 任务被反复打断后无进度锚点。

本模块职责（纯函数 + 状态类, 不依赖 engine 实例）:
- TaskFocusState: 单向切换锁定状态（run 级）
- is_simple_task(): 保守简单任务判定（复杂动词/工具历史/长输入 → 复杂）
- build_task_anchor(): 从会话提取"当前任务目标 + 最近动作"（任务锚点）
- wrap_injection(): 注入统一包装（[上下文注入·非新指令] + 任务锚点）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── 单向切换锁定状态 ──
@dataclass
class TaskFocusState:
    """任务聚焦状态（run 级）.

    escalated: 本 run 已升级到复杂模型（27B）→ 后续轮不切回快模型（9B）。
    同一任务只允许"简单→复杂"单向升级（用户决策 2026-08-22）。
    """

    escalated: bool = False
    anchor_sess: object = field(default=None, repr=False)  # 任务锚点数据源

    def reset(self) -> None:
        """每次 run 开始重置——简单任务首轮仍可切 9B, 复杂后锁定."""
        self.escalated = False

    def mark_escalated(self) -> None:
        """本轮判复杂（切到 27B）→ 锁定本 run 后续轮."""
        self.escalated = True


# ── 简单任务判定 ──
_COMPLEX_VERBS = (
    "配置", "修改", "部署", "实现", "重构", "接入", "集成", "迁移",
    "排查", "分析", "修复", "安装", "设置", "编写", "开发", "创建",
    "添加", "删除", "更新", "优化", "调试", "测试", "检查", "同步",
    "归档", "压缩", "切换", "恢复", "继续", "查看", "读取", "搜索",
)


def is_simple_task(messages: list[dict], max_user_chars: int = 500) -> bool:
    """保守简单任务判定: 本轮用户输入短 + 无工具调用历史 + 非复杂任务指令.

    输入长 / 已出现工具调用（复杂任务信号）/ 指令含复杂任务动词 → 返回 False
    （用默认模型保质量）。阈值 max_user_chars 可经 env LOCAL_FAST_MAX_USER_CHARS 覆盖。
    2026-08-22 收紧: 复杂任务动词识别——"配置/修改/部署/实现/重构/接入/集成/迁移/
    排查/分析"等指令即使短（如"给镜像LFL配置飞书"）也判复杂（实证 98605ad7:
    该指令被误判简单 → 切 9B → 任务漂移）。简单 = 短问题/短说明，无状态变更意图。
    """
    import os

    try:
        max_user_chars = int(os.environ.get("LOCAL_FAST_MAX_USER_CHARS", str(max_user_chars)))
    except (ValueError, TypeError):
        logger.debug("LOCAL_FAST_MAX_USER_CHARS 非法，保留调用方阈值 %s", max_user_chars)
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content") or ""
            last_user = content if isinstance(content, str) else ""
            break
    if not last_user or len(last_user) > max_user_chars:
        return False
    if any(v in last_user for v in _COMPLEX_VERBS):
        return False  # 指令含状态变更意图 → 复杂（不切快模型）
    return all(not (m.get("role") == "tool" or m.get("tool_calls")) for m in messages)


# ── 任务锚点 ──
def build_task_anchor(sess) -> str:
    """从会话最近消息提取"当前任务目标 + 最近动作"（任务锚点）.

    用于注入消息统一包装时附带——AI 被打断（模型切换/记忆/经验注入）后知道
    自己在做什么、做到哪，不再重复探测/绕路。fail-open: 提取失败返回空串。
    """
    try:
        if sess is None or not getattr(sess, "messages", None):
            return ""
        _last_user = ""
        _recent_tools: list[str] = []
        for m in reversed(sess.messages):
            role = getattr(m, "role", "")
            content = str(getattr(m, "content", "") or "")
            if role == "user" and not _last_user and content and not content.startswith("[上下文注入"):
                _last_user = content[:100]
            elif role == "tool" and content and len(_recent_tools) < 2:
                _recent_tools.append(content[:60].replace("\n", " "))
            if _last_user and len(_recent_tools) >= 2:
                break
        _parts = []
        if _last_user:
            _parts.append(f"当前任务: {_last_user}")
        if _recent_tools:
            _parts.append("最近动作: " + " | ".join(_recent_tools))
        return "\n".join(_parts)
    except Exception:  # noqa: BLE001 — fail-open
        return ""


# ── 注入统一包装 ──
_INJECTION_PREFIX = "[上下文注入·非新指令] 继续当前任务，勿当新消息/新指令处理。"


def wrap_injection(content: str, anchor: str = "") -> str:
    """注入统一包装: 系统注入（切换感知/记忆/经验/提醒）统一前缀 + 任务锚点.

    背景（实证 98605ad7）: 注入被 AI 误读为"独立消息/新任务"→ 绕路（"状态已同步
    就绪"/"Let me understand the context"）。统一前缀明确"非新指令, 继续当前任务"——
    AI 不再停下来理解注入, 直接推进任务; 锚点让 AI 知道任务目标/进度。
    """
    if not content or content.startswith(_INJECTION_PREFIX):
        return content
    if anchor:
        return f"{_INJECTION_PREFIX}\n{anchor}\n{content}"
    return f"{_INJECTION_PREFIX}\n{content}"
