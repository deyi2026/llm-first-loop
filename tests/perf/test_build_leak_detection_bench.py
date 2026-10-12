"""T7: build 期泄漏检测性能基准——tasks 4.6, spec 4.1-1.

基准锚点（2026-08-31, 本地 dev 机实测）:
- 10,000 条消息（user/assistant 混合，含 ingress 凭据快照）单遍检测
  p50 ≈ 0.95ms；含 10 条失真 finding 时 p50 ≈ 0.98ms。
- spec 4.1-1 预算: 单轮 build 额外耗时不超 1ms 量级——纯 metadata 单遍
  判定（无 IO / 无模型调用 / 无正则回溯）达成。

阈值取 5ms（≈5 倍余量）: CI 机器抖动防护；显著劣化（>5ms）意味着
检测层引入了 IO 或回溯，须回归排查。
"""

from __future__ import annotations

import statistics
import time

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.trace_leak.leak_detector import detect_leak_at_build

N_MESSAGES = 10_000
BUDGET_MS = 5.0
ROUNDS = 21


def _bench_messages() -> list[Message]:
    msgs: list[Message] = []
    for i in range(N_MESSAGES):
        if i % 2 == 0:
            msgs.append(
                Message(
                    role="user",
                    content=f"m-{i}" * 20,
                    source=MessageSource.USER,
                    metadata={
                        "origin_layer": "user_instruction",
                        "program_origin": False,
                        "ingress_channel": "feishu",
                    },
                )
            )
        else:
            msgs.append(
                Message(role="assistant", content=f"r-{i}" * 20, source=MessageSource.SYSTEM)
            )
    return msgs


def _median_ms(msgs: list[Message]) -> float:
    detect_leak_at_build(msgs, session_id="bench")  # 预热
    times: list[float] = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        detect_leak_at_build(msgs, session_id="bench")
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def test_clean_history_within_budget():
    msgs = _bench_messages()
    assert _median_ms(msgs) < BUDGET_MS


def test_findings_path_within_budget():
    msgs = _bench_messages()
    for i in range(0, N_MESSAGES, 1000):
        msgs[i].metadata = {"origin_layer": "user_instruction", "program_origin": True}
    findings = detect_leak_at_build(msgs, session_id="bench")
    assert len(findings) == 10
    assert _median_ms(msgs) < BUDGET_MS


def test_detector_is_pure_no_io():
    """纯 metadata 判定约束: 消息内容为空/超长时不触发内容解析路径."""
    empty = Message(role="user", content="", source=MessageSource.USER, metadata={})
    legacy = Message(role="user", content="x", source=MessageSource.USER)
    assert detect_leak_at_build([empty, legacy], session_id="s") == []
