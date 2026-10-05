"""S2：profile class 三级授权键（DESIGN-20261005 v4 §4.2）。

三层断言：
1. evaluate_profile_class 纯逻辑全分支（默认档/real 档/ACK 格式/过期/PATHS/mode）
2. BrowserPerceiveTool 回执注记注入（默认档字节级不变；real 档顶层三键）
3. build_engine 工厂门：默认档注册、real 无 ACK 拒绝、real+ACK 注册
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from llm_loop.browser.profile_policy import (
    AckRecord,
    annotation_for,
    ack_digest,
    evaluate_profile_class,
)
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool

TODAY = date(2026, 10, 6)
FUTURE = (TODAY + timedelta(days=30)).strftime("%Y-%m-%d")
PAST = (TODAY - timedelta(days=1)).strftime("%Y-%m-%d")
VALID_ACK = f"yyj|main-profile|{FUTURE}"


# ── 1. evaluate_profile_class ────────────────────────────────────────────


def test_default_tier_empty_dedicated_allowed():
    for klass in ("", "dedicated", "DEDICATED", " Dedicated "):
        d = evaluate_profile_class(klass, "", "", "enforce", today=TODAY)
        assert d.allowed is True
        assert d.profile_class == "dedicated"
        assert annotation_for(d) is None
        assert d.attestation_mode == "enforce"


def test_real_without_ack_refused():
    d = evaluate_profile_class("real", "", "", "enforce", today=TODAY)
    assert d.allowed is False
    assert "REAL_PROFILE_ACK" in d.reason


@pytest.mark.parametrize(
    "ack",
    [
        "only-subject",  # 1 段
        "a|b|c|d",  # 4 段
        "|scope|2026-12-31",  # subject 空
        "subj||2026-12-31",  # scope 空
        "subj|scope|31-12-2026",  # 日期格式
        "subj|scope|2026-13-40",  # 非法日期
        "subj|scope|2026-10-05",  # 昨天=过期（today=2026-10-06）
        f"subj|scope|{PAST}",
    ],
)
def test_real_bad_ack_refused(ack):
    d = evaluate_profile_class("real", ack, "", "enforce", today=TODAY)
    assert d.allowed is False
    assert d.ack is None
    assert "拒绝" in d.reason or "非法" in d.reason or "过期" in d.reason


def test_real_valid_ack_allowed_with_annotation():
    d = evaluate_profile_class("real", VALID_ACK, "", "enforce", today=TODAY)
    assert d.allowed is True
    assert d.profile_class == "real"
    assert d.ack == AckRecord(subject="yyj", scope="main-profile",
                              expires=date.fromisoformat(FUTURE))
    ann = annotation_for(d)
    assert ann is not None
    assert ann["profile_class"] == "real"
    assert ann["ack_digest"] == ack_digest(d.ack)
    assert ann["ack_expires"] == FUTURE


@pytest.mark.parametrize("paths", ["", "none", "/Library/Application Support/Google/Chrome,/tmp/x"])
def test_real_paths_legal_forms_allowed(paths):
    d = evaluate_profile_class("real", VALID_ACK, paths, "enforce", today=TODAY)
    assert d.allowed is True


@pytest.mark.parametrize("paths", ["relative/path", "/abs/ok,bad/rel", "./here"])
def test_real_relative_paths_refused(paths):
    d = evaluate_profile_class("real", VALID_ACK, paths, "enforce", today=TODAY)
    assert d.allowed is False
    assert "相对路径" in d.reason


def test_illegal_class_refused():
    d = evaluate_profile_class("auto", "", "", "enforce", today=TODAY)
    assert d.allowed is False
    assert "PROFILE_CLASS" in d.reason


def test_illegal_mode_refused_even_default_tier():
    d = evaluate_profile_class("", "", "", "loud", today=TODAY)
    assert d.allowed is False
    assert "ATTESTATION_MODE" in d.reason


def test_shadow_mode_allowed_and_recorded():
    d = evaluate_profile_class("real", VALID_ACK, "none", "shadow", today=TODAY)
    assert d.allowed is True
    assert d.attestation_mode == "shadow"


# ── 2. 回执注记注入 ───────────────────────────────────────────────────────


def _tool(profile_annotation=None):
    return BrowserPerceiveTool(
        adapter=object(),
        backend=None,
        session_id_getter=lambda: "s",
        profile_annotation=profile_annotation,
    )


def test_receipt_default_tier_byte_identical():
    payload = json.loads(_tool()._json_result({"x": 1}).content)
    assert payload == {"x": 1}


def test_receipt_real_tier_annotation_top_level():
    ann = {"profile_class": "real", "ack_digest": "ab" * 8, "ack_expires": FUTURE}
    payload = json.loads(_tool(ann)._json_result({"x": 1}).content)
    assert payload["profile_class"] == "real"
    assert payload["ack_digest"] == "ab" * 8
    assert payload["x"] == 1


# ── 3. factory 门 ────────────────────────────────────────────────────────


def _engine(tmp_path, **browser_kw):
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    tag = browser_kw.get("browser_profile_class") or "default"
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / f"data-{tag}"),
        self_inspection_enabled=False,
        extract_enabled=False,
        browser_perception_cdp_url="http://127.0.0.1:39999",
        browser_action_enabled=True,
        **browser_kw,
    )
    return build_engine(settings)  # type: ignore[no-any-return]


def test_factory_gate_three_states(tmp_path):
    # 默认档：注册（行为与 S2 之前一致）
    names = set(_engine(tmp_path).registry.names())
    assert "browser_perceive" in names and "browser_operate" in names
    # real 无 ACK：全部 browser 工具拒绝注册
    names_refused = set(
        _engine(tmp_path, browser_profile_class="real").registry.names()
    )
    assert "browser_perceive" not in names_refused
    assert "browser_operate" not in names_refused
    # real + 合法 ACK：注册
    names_ack = set(
        _engine(
            tmp_path,
            browser_profile_class="real",
            browser_real_profile_ack=VALID_ACK,
        ).registry.names()
    )
    assert "browser_perceive" in names_ack and "browser_operate" in names_ack


def test_factory_gate_refuses_expired_ack(tmp_path):
    names = set(
        _engine(
            tmp_path,
            browser_profile_class="real",
            browser_real_profile_ack=f"yyj|main-profile|{PAST}",
        ).registry.names()
    )
    assert "browser_perceive" not in names and "browser_operate" not in names
