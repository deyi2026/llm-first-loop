"""Session-scoped cache-window truth regressions."""

from llm_loop.core.loop.engine_services.run_state import RunStateManager
from llm_loop.core.run_context import current_session_id


def test_last_cache_window_is_session_scoped():
    mgr = RunStateManager()
    token_a = current_session_id.set("session-a")
    try:
        mgr.bucket().last_cache_window = "window-a"
        mgr.bucket().last_cache_window_model = "glm/a"
    finally:
        current_session_id.reset(token_a)

    token_b = current_session_id.set("session-b")
    try:
        assert mgr.bucket().last_cache_window is None
        assert mgr.bucket().last_cache_window_model == ""
        mgr.bucket().last_cache_window = "window-b"
    finally:
        current_session_id.reset(token_b)

    token_a = current_session_id.set("session-a")
    try:
        assert mgr.bucket().last_cache_window == "window-a"
        assert mgr.bucket().last_cache_window_model == "glm/a"
    finally:
        current_session_id.reset(token_a)


def test_cache_boundary_protection_requires_same_turn_model_and_stable_prefix():
    from types import SimpleNamespace

    from llm_loop.core.loop.build import _cache_boundary_protection

    win = SimpleNamespace(
        cached_tokens=900,
        boundary_chars=5_000,
        boundary_exact=True,
        cached_msgs=[
            {"index": 0, "role": "system", "chars": 1_000, "partial": False},
            {"index": 1, "role": "user", "chars": 2_000, "partial": False},
            {"index": 2, "role": "assistant", "chars": 2_000, "partial": True},
        ],
    )
    state = SimpleNamespace(
        last_cache_window=win,
        last_cache_window_model="glm/glm-5.3-flash",
        last_cache_window_turn_ref=42,
        last_cache_window_stable_fp="stable-a",
    )

    assert _cache_boundary_protection(
        state,
        resolved_label="glm/glm-5.3-flash",
        current_turn_ref=42,
        stable_fp="stable-a",
        system_prompt="S" * 1_000,
    ) == (2, 4_000)

    for kwargs in (
        {"resolved_label": "glm/other"},
        {"current_turn_ref": 43},
        {"stable_fp": "stable-b"},
    ):
        args = {
            "resolved_label": "glm/glm-5.3-flash",
            "current_turn_ref": 42,
            "stable_fp": "stable-a",
            "system_prompt": "S" * 1_000,
        }
        args.update(kwargs)
        assert _cache_boundary_protection(state, **args) == (0, 0)


def test_generic_estimated_cache_boundary_never_becomes_hard_protection():
    """cached_tokens→message 的 generic 估算只能观测，不能阻止 history compaction。"""
    from types import SimpleNamespace

    from llm_loop.core.loop.build import _cache_boundary_protection

    win = SimpleNamespace(
        cached_tokens=9_000,
        boundary_chars=50_000,
        boundary_exact=False,
        cached_msgs=[{"index": 0, "role": "system", "chars": 1_000, "partial": False}],
    )
    state = SimpleNamespace(
        last_cache_window=win,
        last_cache_window_model="deepseek/deepseek-v4-flash",
        last_cache_window_turn_ref=7,
        last_cache_window_stable_fp="same",
    )
    assert _cache_boundary_protection(
        state,
        resolved_label="deepseek/deepseek-v4-flash",
        current_turn_ref=7,
        stable_fp="same",
        system_prompt="S" * 1_000,
    ) == (0, 0)


def test_stable_prefix_fingerprint_includes_projected_tool_surface():
    """system/base 相同但 tools 结构变化时，不得复用上一轮 cache gate 指纹。"""
    from llm_loop.core.history import stable_digest
    from llm_loop.core.prompt_build.stages.base_assembly import run_base_assembly

    class _Monitor:
        def __init__(self):
            self.seen = []

        def preflight(self, _sid, fp):
            self.seen.append(fp)

    def _inject(base, prefix_len, _sid):
        return base, prefix_len

    monitor = _Monitor()
    tool_a = stable_digest([
        {"type": "function", "function": {"name": "read_file", "parameters": {}}}
    ])
    tool_b = stable_digest([
        {"type": "function", "function": {"name": "search_text", "parameters": {}}}
    ])
    a1 = run_base_assembly(
        base=[], system_prompt="sys", session_id="s", sess_message_count=0,
        sess_anchor=0, inject_interop=_inject, cache_monitor=monitor,
        tool_prefix_fp=tool_a,
    )
    a2 = run_base_assembly(
        base=[], system_prompt="sys", session_id="s", sess_message_count=0,
        sess_anchor=0, inject_interop=_inject, cache_monitor=monitor,
        tool_prefix_fp=tool_a,
    )
    b = run_base_assembly(
        base=[], system_prompt="sys", session_id="s", sess_message_count=0,
        sess_anchor=0, inject_interop=_inject, cache_monitor=monitor,
        tool_prefix_fp=tool_b,
    )
    assert a1.stable_fp == a2.stable_fp
    assert b.stable_fp != a1.stable_fp
    assert monitor.seen == [a1.stable_fp, a2.stable_fp, b.stable_fp]
