"""方向 C（2026-08-29）: merge_persisted_tail_injections 纯函数单测.

背景: 持久化 memory 注入（EVO-20260827-f42496bc）形成"用户消息+注入"尾部连
续 user 对（主区 883b4725 实测 510/511），1210 结构触发根因形态。本合并为
build 出口的 wire 级源头消除（storage 不动）。
"""

from llm_loop.core.loop.build import merge_persisted_tail_injections
from llm_loop.core.loop.focus import _INJECTION_PREFIX


def _u(content: str) -> dict:
    return {"role": "user", "content": content}


def _sys() -> dict:
    return {"role": "system", "content": "sys"}


def _inj(text: str = "记忆内容") -> dict:
    return _u(f"{_INJECTION_PREFIX}\n{text}")


class TestMerge:
    def test_basic_merge(self):
        """主区 883b4725 形态: [user"继续", 持久化注入] → 合并单条（逐字保留）."""
        inj = _inj()
        built = [_sys(), _u("继续"), inj]
        ts, kept, removed = merge_persisted_tail_injections(built, set())
        assert ts == 1
        assert removed == [2]
        assert len(kept) == 1
        assert kept[0] is built[1]  # 原地修改（dict 引用复用）
        assert kept[0]["content"] == f"继续\n\n{inj['content']}"

    def test_registered_aggregated_protected(self):
        """动态聚合条（登记 idx）保护不参与合并; 前面的持久化注入照常并入."""
        inj = _inj()
        agg = _u(f"{_INJECTION_PREFIX}\n--- [slot:interop] ---\n协调消息")
        built = [_sys(), _u("任务"), inj, agg]
        ts, kept, removed = merge_persisted_tail_injections(built, {3})
        assert ts == 1
        assert removed == [2]  # 仅持久化注入被并入
        assert len(kept) == 2  # [user+注入合并, 聚合条]
        assert kept[-1] is agg  # 聚合条独立保留（strip 消费对象）

    def test_tail_lt2_noop(self):
        """尾部单条 user: 无合并动作."""
        built = [_sys(), _u("仅一条")]
        ts, kept, removed = merge_persisted_tail_injections(built, set())
        assert ts == 1
        assert kept == [] and removed == []

    def test_group_first_injection_kept(self):
        """群首注入（前一条非 user）保留原位——无并入对象."""
        built = [_sys(), _inj("群首注入"), _u("后续用户")]
        ts, kept, removed = merge_persisted_tail_injections(built, set())
        assert ts == 1
        assert removed == []
        assert len(kept) == 2  # 均保留

    def test_real_user_messages_untouched(self):
        """用户连发真实消息（无注入前缀）不合并——保守语义."""
        built = [_sys(), _u("第一条"), _u("第二条")]
        ts, kept, removed = merge_persisted_tail_injections(built, set())
        assert removed == []
        assert len(kept) == 2

    def test_multi_injection_chain_merge(self):
        """多条持久化注入连排: 全部并入首条 user."""
        i1, i2 = _inj("记忆A"), _inj("记忆B")
        built = [_sys(), _u("继续"), i1, i2]
        ts, kept, removed = merge_persisted_tail_injections(built, set())
        assert ts == 1
        assert removed == [2, 3]
        assert len(kept) == 1
        assert kept[0]["content"] == f"继续\n\n{i1['content']}\n\n{i2['content']}"

    def test_non_user_tail_untouched(self):
        """尾部是 assistant（正常对话轮）: 无群可并（空群起点=len）."""
        built = [_sys(), _u("问"), {"role": "assistant", "content": "答"}]
        ts, kept, removed = merge_persisted_tail_injections(built, set())
        assert ts == 3
        assert kept == [] and removed == []


def test_build_direction_c_remaps_registered_dynamic_entry_after_persisted_merge(tmp_path):
    """Legacy/tool-followup view: removing persisted user must not leave err1210 index stale."""
    from llm_loop.core.injection_labels import InjectionLayer, origin_metadata, render_program_appendix
    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.loop.err1210 import content_prefix_sha
    from tests.unit.test_injection_fingerprint import _build, _engine

    engine, sess = _engine(tmp_path)
    engine._current_turn_ref = None
    persisted = render_program_appendix("persisted reference", InjectionLayer.REFERENCE)
    sess.messages.append(
        Message(
            role="user",
            content=persisted,
            source=MessageSource.USER,
            metadata=origin_metadata(InjectionLayer.REFERENCE, persisted_injection=True),
        )
    )
    engine._tip_tail_messages = [
        Message(role="system", content="dynamic tip", source=MessageSource.SYSTEM)
    ]

    out = _build(engine, sess, [])

    assert len(engine._last_build_injections) == 1
    entry = engine._last_build_injections[0]
    assert 0 <= entry.msg_idx < len(out)
    assert content_prefix_sha(str(out[entry.msg_idx].get("content") or "")) == entry.prefix_sha
    assert persisted in str(out[entry.msg_idx - 1].get("content") or "")
