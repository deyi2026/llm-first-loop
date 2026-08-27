"""缓存窗口镜像（2026-08-24）: 把服务端每轮上报的 cached_tokens 映射回提交载荷的
消息级窗口——缓存覆盖到哪条消息、哪些是新增（miss 区）。

对齐服务端缓存管理逻辑: 前缀缓存按字节前缀命中, cached_tokens = 命中的前缀 token 数
（llama.cpp / DeepSeek / MiniMax 均按此上报）。镜像窗口 = 提交载荷的
[cached 区 | 新增区] 分界; 用字符估算（×2 chars/token, 与 runtime 同源）把 token
边界换算回消息索引。

用途（信息补充决策, RULE-AI-00: 程序给事实, AI 决策）:
- 引用缓存区内信息 = 零额外 prefill（已含在载荷内, KV 复用, 可放心引用）
- 新增信息 = 尾部追加保持命中（miss 仅新增段）
- 中插/压缩/重排 = 断前缀（当次全量 miss——物理必然, 需权衡信息价值）

注意: cached_tokens 的语义是"本次请求与上次请求的公共前缀 token 数"——零历史工具轮
下公共前缀通常只有 system+工具 schema（配对组每轮不同, 属于新增区）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 与 runtime._CHARS_PER_TOKEN_EST 同源（字符/token 估算, 服务端 tokenizer 精度外皆用此）
_CHARS_PER_TOKEN = 2


@dataclass
class CacheWindow:
    """单轮提交载荷的缓存窗口描述（结构化, 供事件日志 + architecture_status）."""

    cached_tokens: int
    prompt_tokens: int
    hit_ratio: float  # cached/prompt（服务端口径）
    total_chars: int  # 提交载荷总字符
    boundary_chars: int  # cached 前缀折合字符（min(total_chars, cached×2)）
    boundary_msg_index: int  # 边界所在消息下标（-1 = 无缓存区）
    cached_msgs: list[dict] = field(default_factory=list)  # [{index, role, chars, partial}]
    new_msgs: list[dict] = field(default_factory=list)  # [{index, role, chars}]

    def summary(self) -> str:
        """单行可读摘要（日志/状态展示用）."""
        if not self.cached_msgs and not self.new_msgs:
            return "（空载荷）"
        cached = f"缓存覆盖至消息#{self.boundary_msg_index}"
        if self.cached_msgs and self.cached_msgs[-1].get("partial"):
            cached += "（部分）"
        return (
            f"{cached} [cached {self.cached_tokens}/{self.prompt_tokens} "
            f"({self.hit_ratio:.0%}) | 新增 {len(self.new_msgs)} 条, "
            f"{self.total_chars - self.boundary_chars} 字符]"
        )


def describe_cache_window(
    messages: list[dict],
    cached_tokens: int,
    prompt_tokens: int,
    chars_per_token: int = _CHARS_PER_TOKEN,
) -> CacheWindow:
    """从提交载荷 + 服务端 cached_tokens 计算缓存窗口（纯函数, fail-open）.

    Args:
        messages: 本轮实际提交给 LLM 的消息列表（dict, 含 role/content）.
        cached_tokens: 服务端上报的命中前缀 token 数（0 = 未命中）.
        prompt_tokens: 服务端上报的输入 token 总数（0 = 未提供, 窗口按无缓存处理）.
        chars_per_token: 字符/token 估算（默认 2, 与 runtime 同源; 测试可覆盖）.

    Returns:
        CacheWindow（消息为空/参数异常 → 空窗口, 不抛异常）.
    """
    try:
        cached_tokens = int(cached_tokens or 0)
        prompt_tokens = int(prompt_tokens or 0)
    except (TypeError, ValueError):
        cached_tokens, prompt_tokens = 0, 0
    if not messages:
        return CacheWindow(cached_tokens, prompt_tokens, 0.0, 0, 0, -1)
    total_chars = sum(len(str(m.get("content") or "")) for m in messages)
    hit_ratio = (cached_tokens / prompt_tokens) if prompt_tokens > 0 else 0.0
    boundary_chars = max(0, min(total_chars, int(cached_tokens * chars_per_token)))

    cached_msgs: list[dict] = []
    new_msgs: list[dict] = []
    boundary_idx = -1
    acc = 0
    for i, m in enumerate(messages):
        c = len(str(m.get("content") or ""))
        role = str(m.get("role") or "")
        if acc >= boundary_chars:
            new_msgs.append({"index": i, "role": role, "chars": c})
        elif acc + c <= boundary_chars:
            cached_msgs.append({"index": i, "role": role, "chars": c, "partial": False})
            boundary_idx = i
        else:
            # 边界落在本条内容中间 → 部分缓存（前 (boundary-acc) 字符命中）
            cached_msgs.append({"index": i, "role": role, "chars": c, "partial": True})
            boundary_idx = i
        acc += c
    return CacheWindow(
        cached_tokens=cached_tokens,
        prompt_tokens=prompt_tokens,
        hit_ratio=hit_ratio,
        total_chars=total_chars,
        boundary_chars=boundary_chars,
        boundary_msg_index=boundary_idx,
        cached_msgs=cached_msgs,
        new_msgs=new_msgs,
    )
