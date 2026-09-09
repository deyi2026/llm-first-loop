"""T1.4 组 RT 测试：路由可观测与指纹落盘闭环（spec 5.3.1/6.4/5.3.3，tasks.md §1.4）.

覆盖：①审计行路由三元组（instance/zone/route）落盘与取值域校验；
②事故归因三问仅凭行内字段可答；③向后兼容；④单一 SoT；
⑤决策/执行口径指纹摘要分列可辨 + 200 截断；⑥fail-open；⑦缺失留痕恰一次。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from llm_loop.core.loop.engine_services.run_state import RunStateManager
from llm_loop.core.loop.engine_services.tool_cycle import ToolCycleService
from llm_loop.core.loop.tool_exec import fingerprint_summary
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.status import ArchitectureStatusProvider
from llm_loop.runtime.route_context import (
    get_route_context,
    reset_route_context,
    set_route_audit_fn,
)


@pytest.fixture(autouse=True)
def _route_env_guard(monkeypatch):
    """路由三元组测试隔离：清进程级缓存与显式 env/审计回调，防跨用例泄漏."""
    for name in ("LFL_INSTANCE", "LFL_ZONE", "LFL_ROUTE"):
        monkeypatch.delenv(name, raising=False)
    reset_route_context()
    set_route_audit_fn(None)
    yield
    reset_route_context()
    set_route_audit_fn(None)


def _read_jsonl(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _provider_with_route(audit_dir):
    """对齐 factory.py 生产接线的 provider（route_fn = 进程级路由上下文）."""
    return ArchitectureStatusProvider(
        audit_dir=audit_dir, route_fn=lambda: get_route_context().__dict__
    )


# ── spec 5.3.1-1a: 三元组落盘 + 越界兜底 ──


def test_r531_1a_triple_fields_present(tmp_path, monkeypatch):
    """任一审计行 JSON 含 instance/zone/route 三键、非缺列；非法显式 unknown 兜底."""
    monkeypatch.setenv("LFL_ZONE", "不存在的区")  # 越界显式值 → unknown 兜底
    monkeypatch.setenv("LFL_ROUTE", "teleport")  # 越界显式值 → unknown 兜底
    p = _provider_with_route(tmp_path)
    p.record_action("phase", "evt", "d1")
    p.record_action("phase", "evt", "d2")
    rows = _read_jsonl(tmp_path / "action_trace.jsonl")
    assert len(rows) == 2
    for row in rows:
        assert {"instance", "zone", "route"} <= set(row)  # 三键存在、非缺列
        assert row["instance"]  # instance 恒可得（hostname-pid 缺省）
        assert row["zone"] == "unknown"  # 非法显式值兜底
        assert row["route"] == "unknown"


# ── spec 5.3.1-1b: 显式 zone 如实落盘、检索完整召回 ──


def test_zone_derives_real_mirror_workspace_name(monkeypatch):
    """llm-first-loop-mirror 目录必须机械归因为镜像，不要求独立 /mirror/ 路径段."""
    import llm_loop.runtime.identity as identity_mod

    monkeypatch.setattr(
        identity_mod,
        "compute_identity",
        lambda: SimpleNamespace(workspace_root="/workspace/llm-first-loop-mirror"),
    )
    ctx = get_route_context()
    assert ctx.zone == "镜像"


def test_entrypoint_route_env_is_honored_and_operator_override_wins(monkeypatch):
    """入口写入的 LFL_ROUTE 是进程事实；显式 operator 值仍由同一 env SoT 覆盖."""
    monkeypatch.setenv("LFL_ROUTE", "web")
    assert get_route_context().route == "web"
    reset_route_context()
    monkeypatch.setenv("LFL_ROUTE", "feishu")
    assert get_route_context().route == "feishu"


def test_r531_1b_zone_mirror_env(tmp_path, monkeypatch):
    """LFL_ZONE=镜像 → 该实例全部行 zone=镜像、检索可完整召回."""
    monkeypatch.setenv("LFL_ZONE", "镜像")
    p = _provider_with_route(tmp_path)
    for i in range(5):
        p.record_action("phase", f"evt{i}", f"d{i}")
    rows = _read_jsonl(tmp_path / "action_trace.jsonl")
    assert len(rows) == 5
    hits = [r for r in rows if r["zone"] == "镜像"]  # 检索 zone=镜像
    assert len(hits) == 5  # 完整召回该实例全部事件


# ── spec 5.3.1-2a: 事故归因三问仅凭行内字段可答 ──


def test_r531_2a_triple_question_answerable(tmp_path, monkeypatch):
    """等价场景审计流仅凭行内字段可答：哪个实例 / 哪个区 / 哪个通道."""
    monkeypatch.setenv("LFL_INSTANCE", "inst-42")
    monkeypatch.setenv("LFL_ZONE", "镜像")
    monkeypatch.setenv("LFL_ROUTE", "web")
    p = _provider_with_route(tmp_path)
    for at in ("llm_decide", "tool_call", "tool.repeat_observed"):
        p.record_action("phase", at, "x")
    rows = _read_jsonl(tmp_path / "action_trace.jsonl")
    ctx = get_route_context()
    assert len(rows) == 3
    for row in rows:
        assert row["instance"] == ctx.instance == "inst-42"  # 哪个实例
        assert row["zone"] == "镜像"  # 哪个区
        assert row["route"] == "web"  # 哪个通道


# ── spec 5.3.1-3a / 6.4.4: 向后兼容 ──


def test_r531_3a_backward_compat(tmp_path):
    """历史行（无三字段）被读方 .get(...,"unknown") 容忍；新行被既有消费路径解析不报错."""
    p = ArchitectureStatusProvider(
        audit_dir=tmp_path,
        route_fn=lambda: {"instance": "i-1", "zone": "主区", "route": "cli"},
    )
    p.record_action("phase", "new_event", "new")
    # 追加一行历史格式（仅既有五键）模拟存量数据
    hist = {
        "ts": "2026-01-01T00:00:00+00:00",
        "phase": "p",
        "action_type": "legacy",
        "detail": "old",
        "session_id": "",
    }
    with (tmp_path / "action_trace.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(hist, ensure_ascii=False) + "\n")
    rows = _read_jsonl(tmp_path / "action_trace.jsonl")
    assert len(rows) == 2
    for row in rows:  # 读侧 .get(..., "unknown") 容忍历史行
        assert row.get("instance", "unknown") in ("unknown", "i-1")
        assert row.get("zone", "unknown") in ("unknown", "主区")
    snap = p.snapshot()  # 既有消费路径解析新行不报错
    assert snap["action_trace"][-1]["zone"] == "主区"
    assert snap["action_trace"][-1]["route"] == "cli"


# ── spec 5.3.1-4a: 单一 SoT，无新增独立路由文件 ──


def test_r531_4a_no_extra_route_file(tmp_path):
    """审计目录无新增独立路由文件——路由信息仅存在于 action_trace.jsonl 行内."""
    p = _provider_with_route(tmp_path)
    p.record_action("phase", "evt", "x")
    p.record_action("phase", "evt", "y")
    # conftest isolated_data_dir 沙箱会在 tmp_path 预建 data/ 子目录，此处只校验审计文件面
    assert not [f.name for f in tmp_path.iterdir() if "route" in f.name]
    assert [f.name for f in tmp_path.glob("*.jsonl")] == ["action_trace.jsonl"]


# ── spec 5.3.1-5a: 决策/执行口径指纹摘要分列可辨 ──


class _StubEngine(ToolCycleService):
    """最小引擎替身（对齐 test_loop_stagnation 风格）：供指纹摘要两侧调用."""

    def __init__(self):
        self._host = self  # 替身自给宿主面
        self._run_state_mgr = RunStateManager()
        ToolCycleService.__init__(self, cast(Any, self))  # 走真实服务装配，避免 stub 字段漂移
        self.registry = SimpleNamespace(failure_guidance_enabled=False)
        self.status = None  # _record_tool_history 的空转面
        self.events: list = []
        self.actions: list = []

    def _run_state(self):
        return self._run_state_mgr.bucket()

    def _append_message_event(self, sess, msg):
        self.events.append(msg)

    def _notify_action(self, *args, **kwargs):
        pass

    def _record_action(self, phase, action, detail):
        self.actions.append((phase, action, detail))


_FP_A = 'read_file|{"path": "a.py"}'
_FP_B = 'read_file|{"path": "b.py"}'


def test_r531_5a_fingerprint_calibers_separated():
    """决策/执行口径事件可分别统计同指纹次数、与注入次数一致（分列不混用）."""
    eng = _StubEngine()
    calls = [
        SimpleNamespace(id="1", name="read_file", arguments={"path": "a.py"}),  # A
        SimpleNamespace(id="2", name="read_file", arguments={"path": "b.py"}),  # B
        SimpleNamespace(id="3", name="read_file", arguments={"path": "a.py"}),  # A
    ]
    # 决策口径（llm_decide）：_resp_summary 的 detail 富含逐调用指纹摘要
    detail = eng._resp_summary(cast(Any, SimpleNamespace(tool_calls=calls, content="")))
    assert detail.count(_FP_A) == 2  # 注入 2 次同参 → 决策口径统计一致
    assert detail.count(_FP_B) == 1
    # 执行口径（tool_loop）：tool_trace 的 fp_summary 字段独立统计
    trace: list[dict] = []
    ok = ToolResult(ToolResultStatus.SUCCESS, "ok", "x", "read_file")
    eng._record_single_receipt(
        SimpleNamespace(messages=[], session_id="route-t"), calls[0], ok, trace, round_index=0
    )
    eng._record_single_receipt(
        SimpleNamespace(messages=[], session_id="route-t"), calls[1], ok, trace, round_index=0
    )
    eng._record_single_receipt(
        SimpleNamespace(messages=[], session_id="route-t"), calls[2], ok, trace, round_index=0
    )
    fps = [t["fp_summary"] for t in trace]
    assert fps.count(_FP_A) == 2  # 执行口径同指纹次数与注入一致
    assert fps.count(_FP_B) == 1
    # 分列不混用：决策口径在 detail 字符串、执行口径在 fp_summary 字段，各自可独立统计
    assert all("fp_summary" in t for t in trace)


# ── spec 5.3.1-5b: 200 字符截断 ──


def test_r531_5b_summary_truncated():
    """超长参数摘要 200 字符截断附省略号（两口径同源 fingerprint_summary）."""
    assert fingerprint_summary("x" * 500) == "x" * 200 + "…"
    assert fingerprint_summary("short") == "short"
    assert fingerprint_summary("") == ""
    # 决策口径集成：超长参数经 _resp_summary 落盘时同样截断
    eng = _StubEngine()
    big = SimpleNamespace(id="1", name="read_file", arguments={"path": "y" * 500})
    detail = eng._resp_summary(cast(Any, SimpleNamespace(tool_calls=[big], content="")))
    assert detail.endswith("…" + "}")  # fp 摘要截断附省略号（外层为名{}包裹）
    assert len(detail) <= len("tool_calls=read_file{}") + 200 + 1  # 可辨识优先于可还原


# ── spec 5.3.3-2: route_fn 异常 fail-open ──


def test_route_fail_open(tmp_path):
    """route_fn 抛异常 → 审计行不丢、三字段 unknown（主审计记录完整性优先）."""

    def _boom():
        raise RuntimeError("route resolve exploded")

    p = ArchitectureStatusProvider(audit_dir=tmp_path, route_fn=_boom)
    p.record_action("phase", "evt", "x")
    rows = _read_jsonl(tmp_path / "action_trace.jsonl")
    assert len(rows) == 1  # 主审计记录不丢
    assert rows[0]["instance"] == "unknown"
    assert rows[0]["zone"] == "unknown"
    assert rows[0]["route"] == "unknown"


# ── spec 6.5.4: 缺失事件留痕恰一次 ──


def test_route_missing_recorded_once(monkeypatch):
    """缺失事件留痕恰一次，二次写入不重复（不逐条刷屏）."""
    missing: list[tuple[str, str, str]] = []
    set_route_audit_fn(lambda phase, at, detail: missing.append((phase, at, detail)))
    ctx1 = get_route_context()  # LFL_ROUTE 未设 → route=unknown → 首次解析留痕
    ctx2 = get_route_context()  # 进程级缓存命中，不重复留痕
    assert ctx1 is ctx2
    assert len(missing) == 1  # 恰一次
    assert missing[0][1] == "route.missing"
    assert "route" in missing[0][2]  # 缺失字段列表入 detail
