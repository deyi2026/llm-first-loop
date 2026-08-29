"""CR-R1.1 批次D（审查项6 补全）: packet 输入面 = 真实注入面（shadow 同构度量）。

glm-minimax-3 实测 24/24 warm_active=0 的根因回归锁: memory 自
EVO-20260827-f42496bc 改为一次性持久化（engine wrap+append 进
sess.messages）后仅 fail-open 才进 _inject_parts，packet 编译输入不含
持久化注入 → warm_tokens 恒 0，shadow 无法预演 enforce（审查项6 同构
语义: shadow 与 enforce 使用同一 compiler 产物，前提是产物覆盖真实
注入面）。
"""
import json
from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from tests.unit.test_injection_fingerprint import _build, _engine


def _snap(sess, content: str, turn_ref: str = "t1") -> None:
    sess.messages.append(
        Message(
            role="user",
            content=f"[上下文注入·非新指令]\n{content}",
            source=MessageSource.USER,
            metadata={
                "injection_kind": "memory_snapshot",
                "turn_ref": turn_ref,
                "persisted_injection": True,
            },
        )
    )


def _telemetry_rows(engine) -> list[dict]:
    tpath = Path(engine.settings.data_dir) / "audit" / "cognitive_telemetry.jsonl"
    if not tpath.exists():
        return []
    return [
        json.loads(ln)
        for ln in tpath.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def test_shadow_packet_covers_persisted_memory(tmp_path, monkeypatch):
    """持久化 memory_snapshot 必须投影进 packet（warm_tokens>0）——shadow 度量可预演 enforce."""
    engine, sess = _engine(tmp_path)  # 默认 cog_runtime_mode=shadow
    monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
    _snap(sess, "[相关记忆] 任务A已完成，正推进批次D")
    _snap(sess, "[相关记忆] 上次评估通过", turn_ref="t2")
    _build(engine, sess, [])  # 空 memory_msgs: 不走 fail-open，仅持久化投影路径
    pcs = [r for r in _telemetry_rows(engine) if r.get("event") == "packet_compile"]
    assert pcs, "shadow 必须发 packet_compile（同构计算）"
    assert any(int(r.get("warm_tokens") or 0) > 0 for r in pcs), (
        "持久化 memory_snapshot 必须投影进 packet（warm_tokens>0）——"
        "否则 shadow 无法预演 enforce（glm-minimax-3 24/24 warm=0 根因回归锁）"
    )


def test_no_snapshot_no_warm(tmp_path, monkeypatch):
    """无持久化快照时 warm 保持 0（投影不虚构内容）."""
    engine, sess = _engine(tmp_path)
    monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
    _build(engine, sess, [])
    pcs = [r for r in _telemetry_rows(engine) if r.get("event") == "packet_compile"]
    assert all(int(r.get("warm_tokens") or 0) == 0 for r in pcs)
