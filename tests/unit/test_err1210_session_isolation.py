"""err1210 P0-A 两会话交错隔离 oracle 测试（.codeartsdoer/specs/err1210_p0_fixes T3）.

旧实现暴露关系登记（spec 5.1.1-2a 红绿验证组，design 1.2.3 机理推演）:
- a1/a2/a7 在旧 Engine-global 实现（六字段为普通实例属性）下必然失败——
  a1: B build 覆盖共享 _last_build_injections → A 剥离读到 B 的 3 条；
  a2: B compact 递增共享 _compact_event_seq → A 错误重获降级机会；
  a7: 六字段驻留 engine.__dict__（property 化后经 shim 落桶，不驻留）；
- a6 因六字段串台同样必失败（独立价值: 显式覆盖共享 _last_history_compacted
  与六字段判定的联动路径，该字段本包只测不改）。
会话身份模拟同 lifecycle.py:84-94 contextvar token set/reset 对；
defer_trace 经 conftest isolated_data_dir（autouse LFL_DATA_DIR）隔离。
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.loop.err1210 import InjectedEntry, SlotKind, content_prefix_sha
from llm_loop.core.loop.focus import _INJECTION_PREFIX
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.run_context import current_session_id
from llm_loop.llm.errors import LLMHTTPError

from .test_model_attribution import _FakeLLMClient, _make_engine, _make_pool, _settings

_PROVIDER_JSON = json.dumps({"zhipu": {
    "base_url": "https://api.zhipu.local/v1", "api_key_env": "ZHIPU_API_KEY",
    "models": {"glm-5": {"context": 300000, "thinking": True, "cost_tier": "low"}},
    "default_model": "glm-5"}})


@contextmanager
def _switch_session(sid: str):
    """contextvar token set/reset 对（与 lifecycle.py:84-94 生产机制同源）."""
    token = current_session_id.set(sid)
    try:
        yield sid
    finally:
        current_session_id.reset(token)


def _mk_engine(tmp_path, monkeypatch, responses):
    monkeypatch.setenv("ZHIPU_API_KEY", "k")
    settings = _settings(tmp_path, model_providers_raw=_PROVIDER_JSON, llm_model="zhipu/glm-5")
    fake = _FakeLLMClient("zhipu/glm-5")
    fake.queue(responses)
    engine = _make_engine(tmp_path, _make_pool(settings, fake, cached={"zhipu": fake}), settings)
    # 语义迁移对齐（修复A 配套，err1210.py _err1210_run_begin 注释）: attempted 键
    # 已从"compact 事件 seq"迁移为"run seq"——本测试直接调 _try_err1210_recovery
    # 不走 engine.run，需模拟 run 入口递增，使 attempted 期望值与真实 run 一致（首个 run → 1）。
    engine._err1210_run_begin()
    return engine, fake


def _e1210() -> LLMHTTPError:
    return LLMHTTPError("400 Invalid parameter", status_code=400,
                        body='{"error":{"code":"1210","message":"Invalid parameter"}}')


def _arm_build(engine, n: int, label: str) -> list[dict]:
    """模拟 build: 2 条真实前缀 + n 条尾部注入消息，并旁路登记 n 条."""
    msgs = [{"role": "user", "content": f"{label} 真实历史消息"},
            {"role": "assistant", "content": f"{label} 真实回答"}]
    entries = []
    for i in range(n):
        content = _INJECTION_PREFIX + f"{label} 注入槽 {i}"
        msgs.append({"role": "user", "content": content})
        entries.append(InjectedEntry(
            msg_idx=len(msgs) - 1, slot_kind=SlotKind.INTEROP,
            prefix_sha=content_prefix_sha(content),
            message_ref=Message(role="system", content=content, source=MessageSource.SYSTEM)))
    engine._last_build_injections = entries
    return msgs


def _compact_event(engine) -> None:
    """模拟 build.py:570-575 compact 事件写点（seq False→True 转变递增，落当前会话桶）."""
    engine._last_history_compacted = True  # 共享字段（本包不改，a6 联动覆盖）
    if not engine._compact_event_was_compacted:
        engine._compact_event_seq = engine._compact_event_seq + 1
    engine._compact_event_was_compacted = True


def _attempt(engine, fake, sid: str, msgs: list[dict]):
    return engine._try_err1210_recovery(
        exc=_e1210(), sess=SimpleNamespace(session_id=sid), messages=msgs,
        tools_param=[], llm_client=fake, chat_model_arg=None, timeout_s=1.0, session_id=sid)


class TestTwoSessionInterleaving:
    def test_interleaved_a1_to_a6(self, tmp_path, monkeypatch):
        engine, fake = _mk_engine(tmp_path, monkeypatch, responses=[_e1210(), _e1210(), _e1210(), _e1210()])
        with _switch_session("A"):
            msgs_a = _arm_build(engine, 5, "A")
            _compact_event(engine)  # A compact → A 桶 seq=1
            assert engine._compact_event_seq == 1
        with _switch_session("B"):
            msgs_b = _arm_build(engine, 3, "B")
            _compact_event(engine)  # B compact → B 桶 seq=1（独立计数）
            assert engine._compact_event_seq == 1
        with _switch_session("A"):
            res_a = _attempt(engine, fake, "A", msgs_a)  # A 1210 到达
            assert res_a.stripped_count == 5  # a1: A 剥离 5 条（非 B 的 3/混合）
            assert engine._compact_event_seq == 1  # a2: A seq 仍 1（B 未污染）
            assert res_a.exhausted is True and engine._err1210_attempted == {"A": 1}
            assert len(engine._deferred_replay_refs) == 5  # A defer 归属 A
        with _switch_session("B"):
            assert engine._deferred_replay_refs == []  # a4: B build 不消费 A defer 槽
            res_b = _attempt(engine, fake, "B", msgs_b)  # B 1210 到达
            assert res_b.stripped_count == 3  # a1: B 剥离 3 条；a6: 共享
            # _last_history_compacted（A build 写 True）下 B 判定与串行基线一致
            assert res_b.exhausted and engine._err1210_attempted == {"A": 1, "B": 1}
            assert len(engine._deferred_replay_refs) == 3  # a6: B defer 归属 B
            res_b2 = _attempt(engine, fake, "B", msgs_b)
            assert res_b2.attempted and res_b2.exhausted  # a3: 会话内防循环（单次重试）
        trace = Path(os.environ.get("LFL_DATA_DIR", "data")) / "audit" / "defer_trace.jsonl"
        events = [json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert all(e["session_id"] != "B" for e in events if e["event"] == "defer_replayed")
        engine._last_active_sid = "A"  # a5: 无上下文回退最近活跃会话桶（out-of-run）
        assert len(engine._deferred_replay_refs) == 5
        engine._last_active_sid = "B"
        assert len(engine._deferred_replay_refs) == 3  # a5: 回退锚点切换 → B 桶

    def test_a7_no_instance_attribute_leak(self, tmp_path, monkeypatch):
        """a7: 六旧属性名均不驻留 engine.__dict__（读写全经 property shim 落桶）."""
        engine, _ = _mk_engine(tmp_path, monkeypatch, responses=[])
        _attrs = {"_last_build_injections": [], "_compact_event_seq": 1,
                  "_compact_event_was_compacted": True,
                  "_last_build_defer_replayed": False,
                  "_deferred_replay_refs": [], "_deferred_replay_slots": set()}
        with _switch_session("A"):
            for attr, value in _attrs.items():
                setattr(engine, attr, value)
        assert [attr for attr in _attrs if attr in engine.__dict__] == []
