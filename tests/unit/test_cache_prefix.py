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
    merged = _build_with_system_injects(sp, [
        _fake_msg("system", "MEM-1: 记忆片段"),
        _fake_msg("system", "[外部协调·from DSH] 20260816-006 请复核"),
    ])
    # system_prompt 主体完整出现（不被截断）
    assert sp in merged, "system_prompt 主体必须完整保留（前缀缓存锚）"
    # 动态段追加在尾部, 且顺序保持
    assert merged.index("MEM-1") > merged.index(sp[:50])
    assert merged.index("20260816-006") > merged.index("MEM-1")


def test_prefix_stable_with_and_without_inbox():
    """4. 前缀稳定: 无注入轮 content 是有注入轮 content 的严格前缀（追加式合并语义）."""
    sp = build_system_prompt()
    base_sys = [_fake_msg("system", "MEM-1: 记忆片段")]
    no_inbox = _build_with_system_injects(sp, base_sys)
    with_inbox = _build_with_system_injects(sp, base_sys + [
        _fake_msg("system", "[外部协调·from DSH] 20260816-006 请复核")
    ])
    # 无注入轮是严格前缀（inbox 在尾部追加, 原前缀字节级保持）
    assert with_inbox.startswith(no_inbox), "有注入轮必须保持无注入轮前缀（追加式合并）"
    assert len(with_inbox) > len(no_inbox)
    assert "20260816-006" in with_inbox[len(no_inbox):]  # inbox 段严格在尾部


def test_system_inject_truncation_still_guarded():
    """5. 防累积上限仍生效: 动态段超限截尾部保留最新（原 P1-FEISHU 意图不变）."""
    sp = build_system_prompt()
    # 构造动态段超限: system_prompt + 大量 system 帧
    heavy = [_fake_msg("system", f"STATE-{i}: " + "x" * 500) for i in range(30)]
    merged = _build_with_system_injects(sp, heavy)
    assert sp in merged, "system_prompt 主体仍完整"
    dyn = merged[len(sp):]
    assert len(dyn) <= 4000 * 1.5 + 100, f"动态段应被上限约束, 实际 {len(dyn)}"
    assert "STATE-29" in merged, "保留最新 state 帧（原意图: 状态帧意义在即时性）"
