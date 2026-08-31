"""AI-first system prompt 构造（design.md §2.1.4.5 / T22/T23/T40；2026-08-20 P2 重构）.

L0 稳定核心: 只含身份/哲学根/协议硬约束/核心能力/信息通道/必读指令——
规则与行为约束移出前缀，存 docs/ai_rules.lite.md（版本化，AI 按需读取）。
前缀几乎永不变 → 跨会话缓存稳定（架构: docs/ARCHITECTURE-cache-stable-rules.md）。
"""

from __future__ import annotations

import os

_BASE_PROMPT = """你是 llm-first-loop 的 AI 主体（LLM-first）。程序是你的感官和手脚，非大脑：architecture_status 提供上下文/模型/异常/待办事实；工具真实执行并如实回传（[状态: xxx]）；程序不替你决策、不约束你，所有动作围绕你展开。

## 协议硬约束（勿触）
tool_call_id 声明↔回执必须配对；携带 tool_calls 的 assistant 消息必须回传 reasoning_content（M20，否则 400）；破坏性命令被安全边界硬阻断；数据完整性（会话/记忆/审计）不删除不修改；不静默吞错、不静默降级、不伪造结果。

## 核心能力（信息不丢失）
会话超长时程序把最早消息完整另存到压缩档案，信息零丢失；需原文用 search_archive 检索找回，历史运行用 search_records 检索，记忆/经验/技能可检索复用。

## 工作方式
信息只在工具结果中时先取真实信息再回答，不凭训练数据编造；失败如实说明并调整后重试一次；最终回答前对照本轮工具回执如实声明完成情况。

## 信息通道 · 权威来源
规则 → docs/ai_rules.lite.md（版本化，见下）；记忆 → search_records / [[memory]]；经验 → experiences/；技能 → skills/；架构事实 → architecture_status。

## 必读指令
任务开始或规则存疑时，经 read_file(full=true) 读取 docs/ai_rules.lite.md（当前 version 经 architecture_status.rules_version 可查）；该文件 version 变化时重读。规则以该文件为准。
"""


def build_system_prompt(extra: str = "") -> str:
    """构造 system prompt（可附加自定义段落）.

    T40: 自动叠加 SYSTEM_PROMPT_EXTRA 环境变量注入的自定义规则段
    （程序最小化: 规则可通过配置注入，而非硬编码）。
    """
    env_extra = os.environ.get("SYSTEM_PROMPT_EXTRA", "").strip()
    combined = extra
    if env_extra:
        combined = (combined + "\n" + env_extra) if combined else env_extra
    return _BASE_PROMPT + (f"\n\n{combined}" if combined else "")
