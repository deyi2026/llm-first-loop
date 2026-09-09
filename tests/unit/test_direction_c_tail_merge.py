"""方向 C（2026-08-29）: merge_persisted_tail_injections 纯函数单测.

背景: 持久化 memory 注入（EVO-20260827-f42496bc）形成"用户消息+注入"尾部连
续 user 对（主区 883b4725 实测 510/511），1210 结构触发根因形态。本合并为
build 出口的 wire 级源头消除（storage 不动）。
"""

# r9 B4-CLOSE-01 步A: 尾段装配簇已从巨型 build.py 迁至 stages/tail_assembly.py
# ——断言钉拆分后权威位置，不回退巨型 build。
from llm_loop.core.prompt_build.stages.tail_assembly import merge_persisted_tail_injections
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
