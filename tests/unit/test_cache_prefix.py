"""缓存命中纪律门禁（EVO-20260816-3eb50cf4，Cache-First）.

用户定调: LLM 请求 token 前缀缓存命中是 agent/大模型项目优先考虑项。
本测试把 docs/development_methodology.md 五章"缓存命中纪律"的关键约束固化为
自动化防回归:

- system_prompt 静态（两次调用字节级一致，无时间/随机动态内容）
- tools schema 顺序稳定（两次生成 JSON 一致，防运行时裁剪漂移）
- 前缀稳定（有/无动态注入轮，system_prompt 主体字节级保持命中）
- system_prompt 主体不被截断（Cache-First 核心: 静态段是前缀缓存锚）

2026-08-16 现场: 修复前 system_prompt=6693 字符 > max_sys_merge_chars=4000，
_append_or_merge 把 system_prompt 主体砍到 200 字符——任何 memory/inbox 注入轮
前缀缓存全毁（本文件 4 号测试即该事故的回归护栏）。
"""

import json
import re

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt import build_system_prompt
from llm_loop.tools.registry import ToolRegistry


def _fake_msg(role: str, content: str) -> Message:
    return Message(role=role, content=content, source=MessageSource.SYSTEM)


def test_system_prompt_static():
    """1. system_prompt 静态: 两次调用字节级一致 + 无时间/随机动态模式."""
    sp1 = build_system_prompt()
    sp2 = build_system_prompt()
    assert sp1 == sp2, "system_prompt 两次调用必须字节级一致（含时间戳/计数器即破坏前缀）"
    # 无动态模式: 日期、uuid、随机
    assert not re.search(r"\d{4}-\d{2}-\d{2}", sp1), "system_prompt 不得含日期"
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", sp1), "system_prompt 不得含 uuid"
    assert not re.search(r"random|uuid|time\.", sp1, re.I), "system_prompt 不得引用动态源"


def test_tools_schema_stable():
    """2. tools schema 顺序稳定: 多次生成 JSON 一致（防运行时裁剪/重排/动态内容漂移）.

    注: 生产全量工具集由 factory.build_engine 装配（重依赖），此处注册代表性真实
    工具验证 schemas() 生成逻辑确定性——注册表内容装配期固定，风险在生成逻辑。
    """
    from llm_loop.tools.builtin.edit_file import EditFileTool
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
    from llm_loop.tools.builtin.read_file import ReadFileTool

    reg = ToolRegistry()
    reg.register(ReadFileTool())
    reg.register(EditFileTool())
    reg.register(ExecuteCommandTool(timeout_s=30))
    assert len(reg.schemas()) >= 3, "注册的真实工具应全部可见（门禁前提）"
    snapshots = [json.dumps(reg.schemas(), ensure_ascii=False, sort_keys=True) for _ in range(3)]
    assert len(set(snapshots)) == 1, (
        "tools schema 多次生成必须一致（运行时裁剪/重排/动态内容会破坏前缀）"
    )


def _build_with_system_injects(sp: str, sys_msgs: list[Message]) -> str:
    """辅助: 经 build_history_messages 合并 system 消息后的 out[0].content."""
    out = build_history_messages(sys_msgs, sp, max_chars=200000)
    assert out and out[0]["role"] == "system"
    return out[0]["content"]


def test_system_prompt_not_truncated_by_dynamic_injects():
    """3. (核心回归) system_prompt 主体永不截断——动态注入只追加尾部.

    修复前 (2026-08-16): system_prompt=6693 > max_sys_merge_chars=4000,
    任何 memory/inbox 合并触发截断分支, 主体被砍到 200 字符 → 前缀缓存全毁.
    修复后: 静态主体完整保留, 只对动态追加段设上限.
    """
    sp = build_system_prompt()
    assert len(sp) > 4000, "前置: system_prompt 已超 max_sys_merge_chars（测试前提成立）"
    out = build_history_messages(
        [_fake_msg("system", "MEM-1: 记忆片段"),
         _fake_msg("system", "[外部协调·from DSH] 20260816-006 请复核")],
        sp, max_chars=200000,
    )
    # 2026-08-18 对齐 DSH: system 主体纯静态（注入不进主体——转独立 user 消息）
    assert out[0]["role"] == "system"
    assert out[0]["content"] == sp, "system 主体字节级静态（跨会话一致——首轮命中稳定段）"
    # 注入转 user——内容仍在（AI 可见）
    users = [m for m in out if m["role"] == "user"]
    assert any("MEM-1" in m["content"] for m in users), "memory 注入转 user 保留"
    assert any("20260816-006" in m["content"] for m in users), "协调注入转 user 保留"


def test_prefix_stable_with_and_without_inbox():
    """4. 前缀稳定: 无注入轮 content 是有注入轮 content 的严格前缀（追加式合并语义）."""
    sp = build_system_prompt()
    base_sys = [_fake_msg("system", "MEM-1: 记忆片段")]
    no_inbox = _build_with_system_injects(sp, base_sys)
    with_inbox = _build_with_system_injects(sp, base_sys + [
        _fake_msg("system", "[外部协调·from DSH] 20260816-006 请复核")
    ])
    # 2026-08-18 对齐 DSH: system 主体跨会话字节一致（注入不进主体——转 user）
    assert no_inbox == with_inbox == sp, "system 主体静态（有无注入轮完全一致——跨会话命中稳定段）"


def test_system_inject_no_merge_no_truncation():
    """5. (2026-08-18 对齐 DSH) 注入转 user——无合并无截断——主体静态不受注入量影响."""
    sp = build_system_prompt()
    # 大量 system 帧（原超限场景）——现在转 user 独立——主体不受影响
    heavy = [_fake_msg("system", f"STATE-{i}: " + "x" * 500) for i in range(30)]
    out = build_history_messages(heavy, sp, max_chars=200000)
    assert out[0]["role"] == "system"
    assert out[0]["content"] == sp, "主体字节静态（不受注入量影响）"
    users = [m for m in out if m["role"] == "user"]
    assert len(users) == 30, "30 个注入帧全部转 user 保留（信息零丢失）"
    assert any("STATE-29" in m["content"] for m in users)
