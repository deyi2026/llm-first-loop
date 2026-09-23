"""EVO-20260923-6fe23c9b 落地单测.

F1: Provider Prompt 影响硬检查——模板段必含 + submit 信号正则命中/不命中。
F2(a): save_experience / method 候选保存强制"可执行当前性验证动作"。
F2(b): 检索行为卡卡龄注记 + 超龄(>14d)稳定降权 + 渲染可见。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from llm_loop.introspection.search import CARD_AGE_DOWNWEIGHT_DAYS, annotate_card_age
from llm_loop.introspection.tools_experience import (
    FRESHNESS_ACTION_ERR,
    freshness_action_ok,
    run_save_experience,
)
from llm_loop.introspection.tools_status import _render_experience_record
from llm_loop.introspection.tools_evolution import _PROMPT_SURFACE_RE
from llm_loop.introspection.tools_evolution_template import run_generate_evolution_template


class _FakeStore:
    """记录 save 调用但不落盘。"""

    def __init__(self):
        self.saved = []

    def save(self, doc):
        self.saved.append(doc)
        return "EXPERIENCE-fake.md"


# ---------- F1 ----------


def test_f1_template_contains_hard_section():
    r = run_generate_evolution_template(None, None, {"title": "测试", "source": "manual"})
    assert r.status.name == "SUCCESS"
    assert "Provider Prompt 影响检查（硬性" in r.content
    assert "L2-2/L2-6" in r.content
    assert "qwen3.8-flash-next" in r.content


def test_f1_prompt_surface_regex_hits():
    for text in ["新增开场附录注入", "调整工具 schema 描述", "program prompt 面", "常驻提醒"]:
        assert _PROMPT_SURFACE_RE.search(text), text


def test_f1_prompt_surface_regex_no_false_positive():
    for text in ["优化重试退避策略", "增加缓存层", "重构日志轮转"]:
        assert not _PROMPT_SURFACE_RE.search(text), text


# ---------- F2(a) ----------


def _ok_save_args(**over):
    args = dict(
        title="t",
        scenario="s",
        solution="当前性验证：先 grep -n DSH_HOME scripts/restart_system.sh 确认行号",
        record_kind="experience",
        verification_state="verified",
        evidence="evidence://v1/x",
    )
    args.update(over)
    return args


def test_f2a_accepts_card_with_freshness_action():
    assert freshness_action_ok("当前性验证：先 grep -n X path 确认")
    assert freshness_action_ok("复现：跑 make test 应得 PASS")
    assert freshness_action_ok("body 含 read_file 路径核对")


def test_f2a_rejects_bare_conclusion():
    assert not freshness_action_ok("重启服务即可恢复，结论如此")
    assert not freshness_action_ok("方案 A 优于方案 B")


def test_f2a_save_experience_blocks_without_action():
    store = _FakeStore()
    ret = run_save_experience(store, **_ok_save_args(solution="重启服务即可恢复"))
    assert isinstance(ret, str) and "可执行的当前性验证动作" in ret
    assert store.saved == []  # 未落盘


def test_f2a_save_experience_passes_with_action():
    store = _FakeStore()
    ret = run_save_experience(store, **_ok_save_args())
    assert not (isinstance(ret, str) and ret.startswith("[参数错误]")), ret
    assert len(store.saved) == 1


def test_f2a_method_candidate_gate():
    import types

    from llm_loop.introspection.registry_experience import _run_save_method_candidate

    class _FakeMethodStore:
        def save_candidate(self, **kw):
            return types.SimpleNamespace(method_ref="method:fake", content_hash="h")

    host = types.SimpleNamespace(
        method_store=_FakeMethodStore(),
        current_episode_ref=lambda: "episode:fake",
        audit=lambda *a, **k: None,
    )
    bad = _run_save_method_candidate({"name": "m2", "description": "纯结论无动作", "body": "b2"}, host)
    assert "可执行的当前性验证动作" in bad.content
    ok = _run_save_method_candidate({"name": "m", "description": "desc grep X 确认", "body": "b"}, host)
    assert "可执行的当前性验证动作" not in ok.content  # 过门（后续 provenance 失败属另一分支）


# ---------- F2(b) ----------


def test_f2b_annotate_downweights_stale():
    now = datetime.now(timezone.utc)
    fresh = {"key": "a", "ts": now.isoformat()}
    stale = {"key": "b", "ts": (now - timedelta(days=CARD_AGE_DOWNWEIGHT_DAYS + 1)).isoformat()}
    rows = annotate_card_age([stale, fresh])
    assert rows[0]["key"] == "a"  # 新卡排前（稳定降权）
    assert rows[1]["card_age_days"] > CARD_AGE_DOWNWEIGHT_DAYS
    assert rows[1]["card_age_downweighted"] is True
    assert "card_age_downweighted" not in rows[0]


def test_f2b_unparseable_ts_no_crash():
    rows = annotate_card_age([{"key": "x", "ts": "not-a-date"}])
    assert rows[0]["key"] == "x"
    assert "card_age_days" not in rows[0]


def test_f2b_stable_within_group():
    now = datetime.now(timezone.utc)
    old1 = {"key": "o1", "ts": (now - timedelta(days=30)).isoformat()}
    old2 = {"key": "o2", "ts": (now - timedelta(days=40)).isoformat()}
    new = {"key": "n", "ts": now.isoformat()}
    rows = annotate_card_age([old1, old2, new])
    assert [r["key"] for r in rows] == ["n", "o1", "o2"]


def test_f2b_render_shows_age():
    rec = {
        "kind": "experience",
        "ts": "2026-09-01T00:00:00+00:00",
        "title": "t",
        "experience_ref": "experience:x",
        "card_age_days": 30,
        "card_age_downweighted": True,
    }
    out = _render_experience_record(rec, "experience")
    assert "卡龄=30d（超龄降权）" in out
