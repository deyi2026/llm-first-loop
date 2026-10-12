"""P6 control-plane model commands must retain their explicit Session owner."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from types import SimpleNamespace

from llm_loop.core.session import SessionStore
from llm_loop.introspection.corrections import CorrectionContext
from llm_loop.introspection.model_command import handle_model_command


def _pool():
    # /model default requires no provider construction or network request.
    return SimpleNamespace(
        get_default_model=lambda: "local/default",
        default_registry_snapshot=lambda: object(),
    )


def test_interleaved_model_commands_write_their_own_sessions(tmp_path):
    """Pause A after its callback is formed; B must not replace A's write owner."""
    ready, release = Event(), Event()
    state = local()

    class InterleavedContext(CorrectionContext):
        def __getattribute__(self, name):
            if name == "model_pool" and getattr(state, "interleave", False):
                state.reads = getattr(state, "reads", 0) + 1
                if state.reads == 2:
                    ready.set()
                    assert release.wait(10), "B command did not complete"
            return super().__getattribute__(name)

    store = SessionStore(tmp_path)
    a = store.load(store.create())
    b = store.load(store.create())
    a.model_override = "local/model-a"
    b.model_override = "local/model-b"
    store.save(a)
    store.save(b)
    ctx = InterleavedContext(model_pool=_pool())

    def run_a():
        state.interleave = True
        state.reads = 0
        return handle_model_command("/model default", ctx, a, store)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_a)
        try:
            assert ready.wait(10), "A did not reach the controlled interleaving"
            result_b = handle_model_command("/model default", ctx, b, store)
        finally:
            release.set()
        result_a = future.result(timeout=10)

    assert result_a is not None and result_a.success
    assert result_b is not None and result_b.success
    assert "local/model-a → default" in result_a.reply
    assert "local/model-b → default" in result_b.reply
    assert a.model_override is None
    assert b.model_override is None
    assert store.load(a.session_id).model_override is None
    assert store.load(b.session_id).model_override is None


def test_model_command_without_session_cannot_invoke_stale_callback(tmp_path):
    store = SessionStore(tmp_path)
    stale_writes = []
    ctx = CorrectionContext(model_pool=_pool())
    # Poison the historical compatibility surface: it must carry no write authority.
    vars(ctx)["session_set_override"] = stale_writes.append
    vars(ctx)["session_model_override"] = "local/stale-model"

    result = handle_model_command("/model default", ctx, None, store)

    assert result is not None and not result.success
    assert not result.changed
    assert stale_writes == []


def test_model_command_does_not_publish_its_session_on_shared_context(tmp_path):
    store = SessionStore(tmp_path)
    session = store.load(store.create())
    session.model_override = "local/owned-model"
    stale_writes = []
    ctx = CorrectionContext(model_pool=_pool())
    stale_callback = stale_writes.append
    vars(ctx)["session_set_override"] = stale_callback
    vars(ctx)["session_model_override"] = "local/stale-model"

    result = handle_model_command("/model default", ctx, session, store)

    assert result is not None and result.success
    assert session.model_override is None
    assert vars(ctx)["session_set_override"] is stale_callback
    assert vars(ctx)["session_model_override"] == "local/stale-model"
    assert stale_writes == []
