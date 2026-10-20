"""EVO-20261020 两条 executing 建议的行为锁定测试。

- EVO-20261020-91de7f8c: browser_operate 身份寻址全量回退（投影窗口外对象可
  grounded）；review 闸门指纹相对时间标签归一化（D23-J 漂移）；发布标签
  确定性归一化（零宽/空白变体不再误拒）。
- EVO-20261020-b1c00127: 子代理 wire 早退路径剥离 ingress 标记；
  LLMProjectionError 快速失败（不再 3 次重放）；熔断/投影失败回执携带
  evidence refs（父代理可无损接管）。
"""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.browser.perception import (
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
)
from llm_loop.llm.errors import LLMProjectionError
from llm_loop.subagent.runner import SubAgentRunner, _strip_ingress_markers
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationTool,
)
from llm_loop.tools.review_host_admission import (
    _browser_binding,
    _canonical,
    _digest,
    _page_visible_text,
    _publish_label_candidates,
    _stable_browser_projection,
    is_publication_button,
)

# ---------------------------------------------------------------------------
# EVO-20261020-b1c00127: runner fixes
# ---------------------------------------------------------------------------


def test_strip_ingress_markers_removes_marker_dicts_only() -> None:
    messages = [
        {"role": "user", "content": "hi", "_active_run_ingress_ref": "5"},
        {"role": "assistant", "content": "plain"},
    ]
    stripped = _strip_ingress_markers(messages)
    assert stripped[0] == {"role": "user", "content": "hi"}
    assert stripped[1] == {"role": "assistant", "content": "plain"}
    # no-op fast path returns the same list object when nothing to strip
    clean = [{"role": "user", "content": "ok"}]
    assert _strip_ingress_markers(clean) is clean


def test_bounded_child_wire_strips_marker_without_compaction() -> None:
    """Non-compaction early return must not leak the ingress marker either."""
    marker_msg = SimpleNamespace(
        to_llm_dict=lambda: {
            "role": "user",
            "content": "task",
            "_active_run_ingress_ref": "0",
        }
    )
    plain = SimpleNamespace(
        to_llm_dict=lambda: {"role": "assistant", "content": "ack"}
    )
    session = SimpleNamespace(messages=[marker_msg, plain], session_id="child-x")
    runner_stub = SimpleNamespace(
        _context_limits_resolver=lambda _label: (10**9, None, 4.0),
        _archive_store=None,
    )
    wire, failure = SubAgentRunner._bounded_child_wire(
        runner_stub,
        session,
        llm=SimpleNamespace(max_tokens=100),
        model_label="test/model",
        tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}],
        archived_once=set(),
    )
    assert failure == ""
    assert wire
    assert not any("_active_run_ingress_ref" in m for m in wire)


def test_collect_evidence_refs_recent_first_dedup_capped() -> None:
    def msg(content: str) -> SimpleNamespace:
        return SimpleNamespace(content=content)

    sess = SimpleNamespace(
        messages=[
            msg("older evidence://v1/" + "a" * 64),
            msg("dup evidence://v1/" + "a" * 64 + " plus new evidence://v1/" + "b" * 64),
            msg("no refs here"),
            msg("latest evidence://v1/" + "c" * 64),
        ]
    )
    refs = SubAgentRunner._collect_evidence_refs(sess, limit=2)
    # newest message first; within one message, appearance order is preserved
    assert refs == [
        "evidence://v1/" + "c" * 64,
        "evidence://v1/" + "a" * 64,
    ]
    all_refs = SubAgentRunner._collect_evidence_refs(sess)
    assert all_refs == [
        "evidence://v1/" + "c" * 64,
        "evidence://v1/" + "a" * 64,
        "evidence://v1/" + "b" * 64,
    ]


def test_projection_error_fails_fast_without_triple_replay(build_test_engine) -> None:
    """LLMProjectionError is a local deterministic wire defect: exactly one call."""
    engine, fake = build_test_engine([])
    runner = SubAgentRunner(
        llm=fake,
        registry=engine.registry,
        session_store=engine.session,
        max_iterations=10,
    )

    def _projection_boom(calls):
        raise LLMProjectionError(
            "provider projection failed structural validation",
            violations=["active_run_ingress_unexpected_marker"],
            provider="fake",
        )

    fake._responses = [_projection_boom] * 4
    result = runner.run(task="触发投影错误", depth=0)
    assert result.outcome == "failed"
    assert len(fake.calls) == 1, "projection error must not be replayed"
    assert "投影违反机械 wire 不变量" in result.final_answer
    assert "active_run_ingress_unexpected_marker" in result.final_answer
    assert "不重放" in result.final_answer or "不做重放" in result.final_answer


# ---------------------------------------------------------------------------
# EVO-20261020-91de7f8c: perception identity_search + operate fallback
# ---------------------------------------------------------------------------


def _bundle_objects(count: int) -> list[dict]:
    objects = []
    for index in range(count):
        objects.append(
            {
                "id": f"el_{index:020x}",
                "kind": "generic",
                "attributes": {"name": f"item-{index}"},
                "grounding_ref": f"bref-{index}",
            }
        )
    # footer publish button beyond any 100-object projection window
    objects.append(
        {
            "id": f"el_{count:020x}",
            "kind": "button",
            "attributes": {"name": "发布", "name_normalized": "发布"},
            "grounding_ref": "bref-publish",
        }
    )
    return objects


def test_identity_search_finds_object_beyond_projection_window(tmp_path) -> None:
    store = BrowserPerceptionStore(tmp_path)
    adapter = BrowserPerceptionAdapter(store=store)
    snapshot_id = "bsnap-1-0123456789abcdef"
    store.persist(
        "sess-x",
        {
            "snapshot": {"snapshot_id": snapshot_id},
            "scope_facts": [],
            "objects": _bundle_objects(1550),
            "object_grounding": {},
            "resource_grounding": {},
            "source_grounding": {},
            "sensor_grounding": {},
        },
    )
    result = adapter.identity_search(
        "sess-x", {"kind": "button", "name": "发布"}, snapshot_id=snapshot_id
    )
    assert result["schema"] == "browser.identity_search.v0.1"
    assert result["total"] == 1
    assert result["objects"][0]["grounding_ref"] == "bref-publish"
    assert result["objects"][0]["kind"] == "button"

    miss = adapter.identity_search(
        "sess-x", {"kind": "button", "name": "不存在"}, snapshot_id=snapshot_id
    )
    assert miss["total"] == 0 and miss["objects"] == []


def _operate_tool_stub(window_objects: list[dict], search_result: dict | None):
    perception = SimpleNamespace(
        snapshot=lambda session_id, raw, projection_limit=100: {
            "objects": window_objects
        },
        identity_search=lambda session_id, identity: search_result,
    )
    capture = SimpleNamespace(capture=lambda: {})
    execute = SimpleNamespace()
    receipts = SimpleNamespace()
    tool = BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=capture,
        semantic_execute=execute,
        receipt_store=receipts,
        session_id_getter=lambda: "sess-op",
    )
    return tool


def test_ground_object_falls_back_to_full_list_search() -> None:
    """A publish button outside the 100-window must still ground by {kind,name}."""
    window = [
        {"kind": "generic", "attributes": {"name": f"item-{i}"}, "grounding_ref": f"r{i}"}
        for i in range(100)
    ]
    search = {
        "schema": "browser.identity_search.v0.1",
        "total": 1,
        "objects": [
            {
                "kind": "button",
                "name": "发布",
                "name_normalized": "发布",
                "grounding_ref": "bref-publish",
            }
        ],
    }
    tool = _operate_tool_stub(window, search)
    ref, count, identity, snapshot_result, detail = tool._ground_object(
        "sess-op",
        {"kind": "object", "identity": {"kind": "button", "name": "发布"}},
    )
    assert count == 1
    assert ref == "bref-publish"
    assert detail.get("matched_via") == "identity_search_full_list"
    assert snapshot_result.get("identity_search") == search


def test_candidate_projection_places_full_search_matches_first() -> None:
    window = [
        {"kind": "generic", "attributes": {"name": f"w{i}"}, "grounding_ref": f"w{i}"}
        for i in range(20)
    ]
    snapshot_result = {
        "objects": window,
        "identity_search": {
            "total": 1,
            "objects": [
                {
                    "kind": "button",
                    "name": "发布",
                    "grounding_ref": "bref-publish",
                }
            ],
        },
    }
    projection = BrowserSemanticOperationTool._candidate_projection(snapshot_result)
    items = projection["items"]
    assert items[0]["grounding_ref"] == "bref-publish"
    assert items[0]["name"] == "发布"
    assert projection["returned"] <= projection["max_projection"]


# ---------------------------------------------------------------------------
# EVO-20261020-91de7f8c: review gate fingerprint / label normalization
# ---------------------------------------------------------------------------


def _editor_raw(time_label: str) -> dict:
    return {
        "url": "https://zhuanlan.zhihu.com/write",
        "dom": {
            "nodes": [
                {"attributes": {"name": time_label}},
                {"attributes": {"value_text": "AI 工程周报第二十三期正文……" * 4}},
                {"attributes": {"name": "发布"}},
            ]
        },
        "ax": {},
    }


def test_page_visible_text_normalizes_drifting_relative_time_labels() -> None:
    a = _page_visible_text(_editor_raw("刚刚 · 草稿"))
    b = _page_visible_text(_editor_raw("1 分钟前 · 草稿"))
    assert a == b
    c = _page_visible_text(_editor_raw("5 min ago"))
    d = _page_visible_text(_editor_raw("6 minutes ago"))
    assert c == d


def test_browser_binding_sha_stable_under_time_label_drift() -> None:
    a = _browser_binding(_editor_raw("刚刚 · 草稿"))
    b = _browser_binding(_editor_raw("2 分钟前 · 草稿"))
    assert a[0] == b[0], "content-identical page must hash identically at review/gate time"
    # projection hash participates in the same normalization
    pa = _digest(_canonical(_stable_browser_projection(_editor_raw("刚刚 · 草稿"))))
    pb = _digest(_canonical(_stable_browser_projection(_editor_raw("1 小时前 · 草稿"))))
    assert pa == pb


def test_publish_label_candidates_strip_zero_width_and_collapse_space() -> None:
    # zero-width bytes inside the visible label must not defeat the gate
    obj = {"kind": "generic", "attributes": {"role": "button", "name": "发\u200b布"}}
    assert _publish_label_candidates(obj)["name"] == "发布"
    assert is_publication_button(obj) is True
    # inner whitespace survives collapse as a single space: "发布 文章" is a
    # different visible label than "发布文章" and stays outside the pattern
    spaced = {"kind": "generic", "attributes": {"role": "button", "name": "发布\u3000文章 "}}
    assert _publish_label_candidates(spaced)["name"] == "发布 文章"
    assert is_publication_button(spaced) is False


def test_publish_button_still_rejects_ambiguous_labels() -> None:
    assert is_publication_button(
        {"kind": "button", "attributes": {"name": "Submit"}}
    ) is False
    assert is_publication_button(
        {"kind": "generic", "attributes": {"role": "button", "name": "保存"}}
    ) is False
    assert is_publication_button(None) is False
