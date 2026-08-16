"""EVO-20260816-37633629 ③: 降级提示 stamp 限频测试.

覆盖:
- helper 层: 首提示注入+写 stamp / 窗口内同类抑制 / cooldown=0 关闭限频 /
  过期 stamp 再提示 / 损坏文件 fail-open / kind 维度隔离
- chain 层: _try_fallback_chain 第二次同类降级不注入提示（审计/status 不受影响由
  既有 test_model_fallback 覆盖——本文件只验消息注入维度）；
  链全失败汇总消息不限频（每次如实告知）

设计原则:
- stamp 路径全部指向 tmp_path（helper 显式传 path，零全局污染、零顺序依赖）
- chain 层用 _FakeEngine(_FallbackMixin) 最小装配（status/corrections=None）
- 零网络、零真实 data/ 写入
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from llm_loop.core.loop.fallback import (
    _fallback_notice_cooldown_s,
    _fallback_notice_suppressed,
    _FallbackMixin,
    _load_notice_stamps,
    _notice_stamp_path,
    _record_fallback_notice,
)
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMTimeoutError

# ── helper 层 ──


def test_stamp_path_derives_from_data_dir(tmp_path: Path) -> None:
    class _S:
        data_dir = str(tmp_path / "data")

    p = _notice_stamp_path(_S())
    assert p == tmp_path / "data" / "state" / "fallback_notice_stamps.json"
    # settings 缺失/无 data_dir → 回退 ./data（不抛异常）
    assert _notice_stamp_path(object()).name == "fallback_notice_stamps.json"


def test_first_notice_not_suppressed_and_record_writes_stamp(tmp_path: Path) -> None:
    p = tmp_path / "stamps.json"
    assert not _fallback_notice_suppressed(p, "a->b")
    _record_fallback_notice(p, "a->b")
    stamps = json.loads(p.read_text(encoding="utf-8"))
    assert "a->b" in stamps
    assert _fallback_notice_suppressed(p, "a->b")


def test_cooldown_zero_disables_throttle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FALLBACK_NOTICE_COOLDOWN_S", "0")
    assert _fallback_notice_cooldown_s() == 0.0
    p = tmp_path / "stamps.json"
    _record_fallback_notice(p, "a->b")
    assert not _fallback_notice_suppressed(p, "a->b")


def test_invalid_cooldown_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FALLBACK_NOTICE_COOLDOWN_S", "not-a-number")
    assert _fallback_notice_cooldown_s() == 86400.0
    monkeypatch.setenv("FALLBACK_NOTICE_COOLDOWN_S", "-5")
    assert _fallback_notice_cooldown_s() == 86400.0


def test_expired_stamp_prompts_again(tmp_path: Path) -> None:
    p = tmp_path / "stamps.json"
    p.write_text(json.dumps({"a->b": time.time() - 90000}), encoding="utf-8")  # 25h 前
    assert not _fallback_notice_suppressed(p, "a->b")


def test_corrupt_stamp_file_fail_open(tmp_path: Path) -> None:
    p = tmp_path / "stamps.json"
    p.write_text("{not json", encoding="utf-8")
    assert not _fallback_notice_suppressed(p, "a->b")  # fail-open: 照常提示
    assert _load_notice_stamps(p) == {}
    # 损坏后仍可重写恢复
    _record_fallback_notice(p, "a->b")
    assert _fallback_notice_suppressed(p, "a->b")


def test_suppression_isolated_per_kind(tmp_path: Path) -> None:
    p = tmp_path / "stamps.json"
    _record_fallback_notice(p, "a->b")
    assert _fallback_notice_suppressed(p, "a->b")
    assert not _fallback_notice_suppressed(p, "a->c")  # 不同降级对不受影响


# ── chain 层（_try_fallback_chain 消息注入维度）──


class _FakeClient:
    def __init__(self, item):
        self._item = item

    def chat(self, messages, tools, timeout_s=None, model=None):
        if isinstance(self._item, Exception):
            raise self._item
        return self._item


class _FakePool:
    def __init__(self, client, refs=("deepseek/backup",)):
        self._client = client
        self._refs = list(refs)

    def fallback_candidates(self):
        return list(self._refs)

    def get_client(self, ref):
        return self._client

    def get_default_model(self):
        return "deepseek/primary"


class _FakeEngine(_FallbackMixin):
    def __init__(self, pool, data_dir: Path):
        self.llm_pool = pool
        self.status = None
        self.corrections = None
        self.actions: list[tuple[str, str, str]] = []

        class _S:
            pass

        self.settings = _S()
        self.settings.data_dir = str(data_dir)

    def _record_action(self, phase: str, action_type: str, detail: str) -> None:
        self.actions.append((phase, action_type, detail))


def _ok_response() -> LLMResponse:
    return LLMResponse(content="ok", tool_calls=[])


def test_chain_first_fallback_injects_notice(tmp_path: Path) -> None:
    engine = _FakeEngine(_FakePool(_FakeClient(_ok_response())), tmp_path)
    resp, msgs, ref = engine._try_fallback_chain(
        messages=[], tools=[], timeout_s=1.0,
        primary_error=LLMTimeoutError("timeout"), session_id="s1",
    )
    assert resp is not None and ref == "deepseek/backup"
    assert len(msgs) == 1 and "[模型降级: deepseek/primary→deepseek/backup" in msgs[0].content


def test_chain_second_same_kind_suppressed(tmp_path: Path) -> None:
    engine = _FakeEngine(_FakePool(_FakeClient(_ok_response())), tmp_path)
    kwargs = dict(messages=[], tools=[], timeout_s=1.0,
                  primary_error=LLMTimeoutError("timeout"), session_id="s1")
    _, msgs1, _ = engine._try_fallback_chain(**kwargs)
    _, msgs2, _ = engine._try_fallback_chain(**kwargs)
    assert len(msgs1) == 1
    assert msgs2 == []  # 24h 内同类降级提示仅一次（nudge without nagging）
    suppressed = [a for a in engine.actions if a[1] == "fallback_notice_suppressed"]
    assert len(suppressed) == 1 and "deepseek/primary->deepseek/backup" in suppressed[0][2]


def test_chain_all_failed_summary_never_throttled(tmp_path: Path) -> None:
    engine = _FakeEngine(
        _FakePool(_FakeClient(LLMTimeoutError("backup also down"))), tmp_path
    )
    kwargs = dict(messages=[], tools=[], timeout_s=1.0,
                  primary_error=LLMTimeoutError("timeout"), session_id="s1")
    resp1, msgs1, _ = engine._try_fallback_chain(**kwargs)
    resp2, msgs2, _ = engine._try_fallback_chain(**kwargs)
    assert resp1 is None and resp2 is None
    assert len(msgs1) == 1 and len(msgs2) == 1  # 全失败汇总每次如实注入，不限频
