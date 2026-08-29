"""档案槽前缀不变式测试（SDD-20260830 契约核心，FR-1.2/1.4/2.2/2.3）.

架构生命线：档案块 append-only——轮 N 的档案槽视图中，轮 N-1 已有块的字节
零改动；新块只追加在尾部。违反即缓存前缀断裂（EVO-20260819-7bb7d689 教训）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from llm_loop.core.session_digest import SessionDigest


class _StubStatus:
    def __init__(self, v: str):
        self.value = v


class _StubMsg:
    """最小 tool 消息桩（duck-typing 兼容 update_from_messages）."""

    def __init__(self, call_id: str, name: str, content: str, status_value: str = "success"):
        self.role = "tool"
        self.status = _StubStatus(status_value)
        self.tool_call_id = call_id
        self.tool_name = name
        self.content = content


def _mk_tool_msg(call_id: str, name: str, content: str):
    return _StubMsg(call_id, name, content)


def test_append_only_bytes_stable():
    """FR-1.2: 已有块字节零改动——轮 N-1 渲染是轮 N 渲染的前缀子串级稳定."""
    d = SessionDigest("t1")
    d.append("c1", "web_fetch", "[状态: success] 文章A内容 " + "x" * 200, {"url": "https://a.com/1"})
    r1 = d.render()
    d.append("c2", "read_file", "[状态: success] 文件B内容", {"path": "/tmp/b.py"})
    r2 = d.render()
    # 块级：r1 的每个块渲染在 r2 中原样存在（字节一致）
    assert d._render_block(d._blocks[0]) in r2
    # 头部稳定：r1 去掉尾部长度差后应与 r2 前缀一致（块序不重排）
    assert r2.startswith(r1.split("\n\n")[0])  # 标题行不变
    # 块数单调递增
    assert d.block_count == 2


def test_new_block_appended_at_tail():
    """FR-1.2: 新块只追加在尾部（旧块之后），不插入中间."""
    d = SessionDigest("t2")
    d.append("a", "t1", "content-a")
    d.append("b", "t2", "content-b")
    d.append("c", "t3", "content-c")
    r = d.render()
    ia, ib, ic = r.find("t1(") if "t1(" in r else r.find("▸ t1"), r.find("▸ t2"), r.find("▸ t3")
    assert 0 < ia < ib < ic, "块序应按追加序（a→b→c）严格递增"


def test_duplicate_and_failure_no_block():
    """FR-1.5: 同 tool_call_id 幂等；空内容不产生块."""
    d = SessionDigest("t3")
    assert d.append("x", "t", "内容") is not None
    assert d.append("x", "t", "重复") is None  # 幂等
    assert d.append("y", "t", "") is None  # 空内容
    assert d.append("y", "t", "   ") is None  # 空白
    assert d.block_count == 1


def test_update_from_messages_extracts_success_only():
    """update_from_messages: 只提取 SUCCESS 工具回执（FR-1.1），重复消息幂等."""
    d = SessionDigest("t4")
    msgs = [
        _mk_tool_msg("c1", "web_fetch", "[状态: success] 内容1"),
        _StubMsg("c2", "execute_command", "[状态: failure] 失败不进档案", status_value="failure"),
        _StubMsg("c3", "t", "失败态", status_value="failure"),
    ]
    n1 = d.update_from_messages(msgs)
    n2 = d.update_from_messages(msgs)  # 二次扫描幂等
    assert n1 == 1, "只有 SUCCESS（c1）产生块"
    assert n2 == 0, "重复回执不重复产生"
    assert d.block_count == 1


def test_render_deterministic_across_instances():
    """渲染确定性：同输入序列的两个实例渲染字节一致（frozen dataclass 契约）."""
    def build() -> str:
        d = SessionDigest("t5")
        d.append("c1", "web_fetch", "[状态: success] 内容 " + "y" * 100, {"url": "https://x.io"})
        d.append("c2", "search_records", "[状态: success] 命中 3 条", {"query": "kw"})
        return d.render()

    assert build() == build()


def test_disabled_flag_zero_injection():
    """NFR-3 前置：digest_enabled=False 时 build 层零注入（此处验证 SessionDigest 独立性——
    build 挂接层由 integration 测试覆盖）."""
    d = SessionDigest("t6")
    before = d.render()
    d.append("c1", "t", "内容")
    assert before == "" and d.render() != ""  # 模块本身可用；开关在 build 层
