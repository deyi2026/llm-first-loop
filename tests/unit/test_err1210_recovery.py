"""err1210 P0 恢复回归测试（.codeartsdoer/specs/err1210_locating，tasks 1.3/2.4/3.7/5.x）.

覆盖:
- T1.3 payload_trace 按日轮转 + 过期清理 + 无代码读取方固化
- T2.4 三函数边界（parse_provider_error_code / reset_hotcard_consumed / restore_gate_note）
- exact 1210 classification + bounded tail-user wire normalization
- no-transform zero retry / changed-payload one retry / per-run exhaustion

零真实网络（_FakeLLMClient 可编程异常队列）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from llm_loop.core.cache_health import CacheHealthMonitor
from llm_loop.core.loop.engine_services.recovery_controller import RecoveryController
from llm_loop.core.loop.err1210 import is_err1210, snapshot_offending_payload
from llm_loop.core.loop.hotcard import (
    hotcard_path,
    pop_hotcard,
    reset_hotcard_consumed,
    write_hotcard,
)
from llm_loop.llm.client import _cleanup_trace_shards, _maybe_rotate_trace_file
from llm_loop.llm.errors import LLMHTTPError, parse_provider_error_code

from .test_model_attribution import (
    _FakeLLMClient,
    _make_engine,
    _make_pool,
    _settings,
)

_ERR1210_BODY = '{"error":{"code":"1210","message":"Invalid parameter"}}'


def _e1210() -> LLMHTTPError:
    return LLMHTTPError("400 Invalid parameter", status_code=400, body=_ERR1210_BODY)


# ── T1.3: payload_trace 轮转 ──


class TestTraceRotation:
    def test_rotate_on_cross_day_mtime(self, tmp_path, monkeypatch):
        active = tmp_path / "payload_trace.jsonl"
        active.write_text('{"a":1}\n', encoding="utf-8")
        # 伪造昨日 mtime
        old = time.time() - 86400 * 2
        os.utime(active, (old, old))
        import llm_loop.llm.client as client_mod

        monkeypatch.setattr(client_mod, "_TRACE_ROTATE_LAST_CHECK", 0.0)
        out = _maybe_rotate_trace_file(str(active))
        assert out == str(active)
        shards = list(tmp_path.glob("payload_trace-*.jsonl"))
        assert len(shards) == 1
        assert not active.exists() or active.read_text() == ""  # 活跃文件已切走

    def test_no_rotate_same_day(self, tmp_path, monkeypatch):
        active = tmp_path / "payload_trace.jsonl"
        active.write_text('{"a":1}\n', encoding="utf-8")
        import llm_loop.llm.client as client_mod

        monkeypatch.setattr(client_mod, "_TRACE_ROTATE_LAST_CHECK", 0.0)
        _maybe_rotate_trace_file(str(active))
        assert active.exists()
        assert not list(tmp_path.glob("payload_trace-*.jsonl"))

    def test_throttled_within_hour(self, tmp_path, monkeypatch):
        active = tmp_path / "payload_trace.jsonl"
        active.write_text('{"a":1}\n', encoding="utf-8")
        old = time.time() - 86400 * 2
        os.utime(active, (old, old))
        import llm_loop.llm.client as client_mod

        monkeypatch.setattr(client_mod, "_TRACE_ROTATE_LAST_CHECK", time.time() - 60)
        _maybe_rotate_trace_file(str(active))
        assert active.exists()  # 节流期内不实际检查

    def test_cleanup_expired_shards(self, tmp_path, monkeypatch):
        active = tmp_path / "payload_trace.jsonl"
        active.write_text("{}", encoding="utf-8")
        stale = tmp_path / "payload_trace-20200101.jsonl"
        stale.write_text("{}", encoding="utf-8")
        old = time.time() - 86400 * 30  # 清理按 mtime 判定（文件名仅命名约定）
        os.utime(stale, (old, old))
        fresh = tmp_path / "payload_trace-20990101.jsonl"
        fresh.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("LLM_PAYLOAD_TRACE_RETAIN_DAYS", "7")
        _cleanup_trace_shards(active)
        assert not stale.exists()
        assert fresh.exists()

    def test_no_code_reader_regression(self):
        """固化'全仓无 payload_trace 代码读取方'事实（防未来新增读取方忽略跨分片聚合）."""
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[2]
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "import subprocess,sys\n"
                "out = subprocess.run(['git','-C',sys.argv[1],'grep','-n','payload_trace','--','src/'],\n"
                "                     capture_output=True, text=True).stdout\n"
                "lines = [l for l in out.splitlines() if 'payload_trace' in l]\n"
                "print('\\n'.join(lines))",
                str(root),
            ],
            capture_output=True,
            text=True,
        )
        hits = [line for line in r.stdout.splitlines() if line.strip()]

        def _is_comment_ref(line: str) -> bool:
            # git grep 输出格式 src/path:lineno:content——注释行（# 开头）是说明性引用非读取方
            content = line.split(":", 2)[-1].lstrip()
            return content.startswith("#")

        # 允许: ① client.py 写入侧本体（trace 函数/轮转/清理/诊断）② 任意文件的注释性提及
        # （如 err1210.py trace_key 注释——git grep 只搜 tracked 文件，e9a2e6b 落库后
        # 该注释进入扫描范围；本测试防的是"读取方代码"，注释不构成读取）
        allowed = all(
            (("llm/client.py" in line or "llm\\client.py" in line) or _is_comment_ref(line))
            and "read" not in line.lower()
            for line in hits
        )
        assert allowed, f"payload_trace 出现了写入侧之外的引用:\n{chr(10).join(hits)}"

    def test_wildcard_aggregation(self, tmp_path, monkeypatch):
        """轮转后 payload_trace*.jsonl 通配聚合可覆盖活跃+历史分片（离线消费习惯）."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "payload_trace.jsonl").write_text('{"i":1}\n', encoding="utf-8")
        (tmp_path / "payload_trace-20200101.jsonl").write_text('{"i":0}\n', encoding="utf-8")
        rows = []
        for p in sorted(tmp_path.glob("payload_trace*.jsonl")):
            rows.extend(
                json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()
            )
        assert [r["i"] for r in rows] == [0, 1]


# ── T2.4: 三函数边界 ──


class TestParseProviderErrorCode:
    def test_plain_json(self):
        assert parse_provider_error_code(_ERR1210_BODY) == "1210"

    def test_escaped_json_string(self):
        body = json.dumps(_ERR1210_BODY)  # '"{\\"error\\":{...}}"'
        assert parse_provider_error_code(body) == "1210"

    def test_double_escaped(self):
        body = json.dumps(json.dumps(_ERR1210_BODY))
        assert parse_provider_error_code(body) == "1210"

    def test_prefix_suffix_noise(self):
        body = f"upstream said: {_ERR1210_BODY} (truncated)"
        assert parse_provider_error_code(body) == "1210"

    def test_empty_and_garbage(self):
        assert parse_provider_error_code("") is None
        assert parse_provider_error_code("not json at all") is None
        assert parse_provider_error_code('{"error":{"code":"abc"}}') == "abc"
        assert parse_provider_error_code('{"other":1}') is None


class TestResetHotcardConsumed:
    def test_reset_and_repop(self, tmp_path):
        write_hotcard(origin_session="other-sess", anchor="任务A", data_dir=tmp_path)
        text = pop_hotcard(session_id="sess-1", data_dir=tmp_path, authorized=True)
        # R3 pointer contract: old action prose stays in the durable card, explicit view is 2-line pointer.
        assert text and "anchor=1" in text and "ref=file:" in text
        assert "任务A" not in text
        card = json.loads(hotcard_path(tmp_path).read_text(encoding="utf-8"))
        assert card["consumed"] is True
        # 默认 reset 无授权 → 不得复活。
        assert reset_hotcard_consumed(session_id="sess-1", data_dir=tmp_path) is False
        assert (
            reset_hotcard_consumed(session_id="sess-1", data_dir=tmp_path, authorized=True) is True
        )
        card = json.loads(hotcard_path(tmp_path).read_text(encoding="utf-8"))
        assert card["consumed"] is False and card["consumed_by"] == ""
        # 复位后仍需再次显式授权才能 pop；build 不会调用此路径。
        again = pop_hotcard(session_id="sess-1", data_dir=tmp_path, authorized=True)
        assert again == text

    def test_stale_card_not_reset(self, tmp_path):
        write_hotcard(origin_session="other-sess", anchor="任务A", data_dir=tmp_path)
        pop_hotcard(session_id="sess-1", data_dir=tmp_path, authorized=True)
        # 不同会话请求复位 → 拒绝（防复活已被新事件接管的卡）
        assert (
            reset_hotcard_consumed(session_id="sess-2", data_dir=tmp_path, authorized=True) is False
        )

    def test_missing_card_returns_false(self, tmp_path):
        assert reset_hotcard_consumed(session_id="s", data_dir=tmp_path) is False

    def test_idempotent_double_reset(self, tmp_path):
        write_hotcard(origin_session="o", anchor="a", data_dir=tmp_path)
        pop_hotcard(session_id="s1", data_dir=tmp_path, authorized=True)
        assert reset_hotcard_consumed(session_id="s1", data_dir=tmp_path, authorized=True) is True
        assert (
            reset_hotcard_consumed(session_id="s1", data_dir=tmp_path, authorized=True) is False
        )  # 已复位


class TestRestoreGateNote:
    def test_restore_then_take(self):
        mon = CacheHealthMonitor()
        sid = "sess-x"
        assert mon.take_gate_note(sid) is False  # 无标记
        mon.restore_gate_note(sid)  # 对不存在桶 fail-open 置位
        assert mon.take_gate_note(sid) is True
        assert mon.take_gate_note(sid) is False  # 一次性


# ── T3.7: 模块级 ──


class TestIsErr1210:
    def test_positive(self):
        assert is_err1210(_e1210()) is True

    def test_negative_status(self):
        e = LLMHTTPError("x", status_code=500, body=_ERR1210_BODY)
        assert is_err1210(e) is False

    def test_negative_code(self):
        e = LLMHTTPError("x", status_code=400, body='{"error":{"code":"1211"}}')
        assert is_err1210(e) is False

    def test_negative_unparseable(self):
        e = LLMHTTPError("x", status_code=400, body="")
        assert is_err1210(e) is False


class TestTailUserNormalization:
    def test_lossless_tail_merge_changes_only_wire_shape(self):
        ctl = RecoveryController(object())  # helper does not consume host
        msgs = [
            {"role": "system", "content": "S"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "U1"},
            {"role": "user", "content": "U2"},
            {"role": "user", "content": "U3"},
        ]
        out = ctl._aggregate_tail_users(msgs)
        assert out is not None
        assert out[:2] == msgs[:2]
        assert len(out) == 3
        assert out[-1]["role"] == "user"
        assert out[-1]["content"].split(ctl._AGG_SEPARATOR) == ["U1", "U2", "U3"]
        assert msgs[-1]["content"] == "U3"  # copy-on-write

    def test_single_tail_user_needs_no_transform(self):
        ctl = RecoveryController(object())
        assert ctl._aggregate_tail_users([{"role": "user", "content": "U"}]) is None

    def test_non_string_or_over_bound_fails_open(self):
        ctl = RecoveryController(object())
        assert (
            ctl._aggregate_tail_users(
                [{"role": "user", "content": "a"}, {"role": "user", "content": {"x": 1}}]
            )
            is None
        )
        assert (
            ctl._aggregate_tail_users([{"role": "user", "content": str(i)} for i in range(17)])
            is None
        )


_PROVIDER_JSON = json.dumps(
    {
        "zhipu": {
            "base_url": "https://api.zhipu.local/v1",
            "api_key_env": "ZHIPU_API_KEY",
            "models": {"glm-5": {"context": 300000, "thinking": True, "cost_tier": "low"}},
            "default_model": "glm-5",
        },
    }
)


def _mk(tmp_path, monkeypatch, *, responses):
    monkeypatch.setenv("ZHIPU_API_KEY", "k")
    settings = _settings(
        tmp_path,
        model_providers_raw=_PROVIDER_JSON,
        llm_model="zhipu/glm-5",
        history_max_chars=300_000,
    )
    fake = _FakeLLMClient("zhipu/glm-5")
    fake.queue(responses)
    pool = _make_pool(settings, fake, cached={"zhipu": fake})
    engine = _make_engine(tmp_path, pool, settings)
    return engine, fake


def _resp(content="恢复后的正常回答"):
    from llm_loop.llm.client import LLMResponse

    return LLMResponse(content=content, tool_calls=[], provider="fake")


class TestMechanicalRecovery:
    def test_modern_single_user_1210_does_not_blind_retry(self, tmp_path, monkeypatch):
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210()])
        sid = engine.session.create()
        result = engine.run(sid, "真实用户任务")
        assert "LLM 调用异常" in result.final_answer
        assert len(fake.calls) == 1
        assert not any(
            a.get("action_type") == "aggregate_retry"
            for a in engine.status.snapshot().get("action_trace", [])
        )

    def test_changed_payload_retries_once_and_recovers(self, tmp_path, monkeypatch):
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_resp("聚合后成功")])
        sid = engine.session.create()
        engine._recovery._err1210_run_begin()
        sess = engine.session.load(sid)
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "U1"},
            {"role": "user", "content": "U2"},
        ]
        out = engine._recovery._try_err1210_recovery(
            exc=_e1210(),
            sess=sess,
            messages=messages,
            tools_param=[],
            llm_client=fake,
            chat_model_arg=None,
            timeout_s=10.0,
            session_id=sid,
            model_label="zhipu/glm-5",
        )
        assert out.recovered is True
        assert out.provider_retry_count == 1
        assert out.transformed_tail_users == 2
        assert len(fake.calls) == 1
        assert len(fake.calls[0]["messages"]) == 2
        assert fake.calls[0]["messages"][-1]["content"].split(engine._recovery._AGG_SEPARATOR) == [
            "U1",
            "U2",
        ]

    def test_changed_payload_still_1210_exhausts_after_one_retry(self, tmp_path, monkeypatch):
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210()])
        sid = engine.session.create()
        engine._recovery._err1210_run_begin()
        sess = engine.session.load(sid)
        out = engine._recovery._try_err1210_recovery(
            exc=_e1210(),
            sess=sess,
            messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
            tools_param=[],
            llm_client=fake,
            chat_model_arg=None,
            timeout_s=10.0,
            session_id=sid,
            model_label="zhipu/glm-5",
        )
        assert out.recovered is False and out.exhausted is True
        assert out.provider_retry_count == 1
        assert len(fake.calls) == 1

    def test_recovery_disabled_makes_zero_provider_calls(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ERR1210_RECOVERY", "0")
        engine, fake = _mk(tmp_path, monkeypatch, responses=[])
        sid = engine.session.create()
        engine._recovery._err1210_run_begin()
        out = engine._recovery._try_err1210_recovery(
            exc=_e1210(),
            sess=engine.session.load(sid),
            messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
            tools_param=[],
            llm_client=fake,
            chat_model_arg=None,
            timeout_s=10.0,
            session_id=sid,
        )
        assert out.attempted is False and out.provider_retry_count == 0
        assert fake.calls == []

    def test_same_run_second_recovery_is_blocked_mechanically(self, tmp_path, monkeypatch):
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_resp("first")])
        sid = engine.session.create()
        engine._recovery._err1210_run_begin()
        kwargs = dict(
            exc=_e1210(),
            sess=engine.session.load(sid),
            messages=[{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
            tools_param=[],
            llm_client=fake,
            chat_model_arg=None,
            timeout_s=10.0,
            session_id=sid,
        )
        first = engine._recovery._try_err1210_recovery(**kwargs)
        second = engine._recovery._try_err1210_recovery(**kwargs)
        assert first.recovered is True
        assert (
            second.attempted is True
            and second.exhausted is True
            and second.provider_retry_count == 0
        )
        assert len(fake.calls) == 1


def test_snapshot_is_diagnostic_only_without_injection_span(tmp_path, monkeypatch):
    monkeypatch.setenv("ERR1210_SNAPSHOT", "1")
    p = snapshot_offending_payload(
        messages=[{"role": "user", "content": "x"}],
        tools=[],
        params={"round_no": 1},
        session_id="s12345678",
        model="zhipu/glm-5",
        data_dir=tmp_path,
    )
    assert p is not None
    row = json.loads(p.read_text(encoding="utf-8"))
    assert row["schema"] == 2
    assert row["recovery_contract"] == "tail_user_normalization_only"
    assert "injection_span" not in row


def test_retired_recovery_control_plane_absent():
    import llm_loop.core.loop.err1210 as err
    from llm_loop.core.loop.engine_services.recovery_controller import RecoveryController

    for name in (
        "_strip_tail_injections",
        "_defer_store",
        "_note_defer_replayed",
        "_err1210_try_runtime_retry",
    ):
        assert not hasattr(RecoveryController, name)
    for name in (
        "InjectedEntry",
        "InjectionSpan",
        "SlotKind",
        "record_defer_event",
        "content_prefix_sha",
    ):
        assert not hasattr(err, name)
