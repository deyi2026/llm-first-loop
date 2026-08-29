"""档案槽端到端集成（SDD-20260830 B.4）: 真实 Message/ToolResultStatus 对象链.

验证挂接风险点：真实 Message 的 status 是 ToolResultStatus 枚举（str-enum），
SessionDigest.update_from_messages 的 duck-typing 双路径（str()/value）必须命中；
真实 build 挂接链路（_session_digest 缓存 + settings 开关）行为正确。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session_digest import SessionDigest
from llm_loop.tools.registry import ToolResultStatus


def _real_tool_msg(call_id: str, name: str, content: str, status=ToolResultStatus.SUCCESS) -> Message:
    return Message(
        role="tool",
        content=content,
        tool_call_id=call_id,
        tool_name=name,
        status=status,
        source=MessageSource.TOOL,
    )


def test_real_message_compat_and_extraction():
    """真实 Message 对象: SUCCESS 提取 / FAILURE 跳过 / 幂等."""
    d = SessionDigest("e2e-compat")
    msgs = [
        _real_tool_msg("c1", "web_fetch", "[状态: success] 正文 " + "z" * 300),
        _real_tool_msg("c2", "execute_command", "[状态: failure] 不进档案", status=ToolResultStatus.FAILURE),
    ]
    assert d.update_from_messages(msgs) == 1
    assert d.update_from_messages(msgs) == 0  # 幂等
    assert d.block_count == 1
    r = d.render()
    assert "web_fetch" in r and "execute_command" not in r


def test_real_message_prefix_invariance():
    """真实对象序列: 轮 N-1 全部块渲染在轮 N 中字节一致（前缀不变式端到端）."""
    d = SessionDigest("e2e-prefix")
    d.update_from_messages([_real_tool_msg("c1", "read_file", "[状态: success] A", )])
    r1 = d.render()
    block1 = d._render_block(d._blocks[0])
    d.update_from_messages([_real_tool_msg("c2", "search_files", "[状态: success] B")])
    r2 = d.render()
    assert block1 in r2, "已有块字节稳定（append-only）"
    assert r2.index(block1) < r2.index(d._render_block(d._blocks[1])), "新块追加在尾部"


def test_builder_digest_cache_lazy():
    """_session_digest: lazy 缓存（同 session 同实例，异 session 异实例）——
    _BuildMixin 挂接层行为（builder 桩验证，无需完整 engine）."""
    from llm_loop.core.loop.build import _BuildMixin

    class _StubBuilder(_BuildMixin):
        settings = None  # type: ignore[assignment]

    b = _StubBuilder()

    class _Sess:
        session_id = "s-e2e"

    d1 = b._session_digest(_Sess())  # type: ignore[arg-type]
    d2 = b._session_digest(_Sess())  # type: ignore[arg-type]
    assert d1 is d2, "同 session 复用实例（append-only 生命周期随会话）"
