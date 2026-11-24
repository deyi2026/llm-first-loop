"""Exercise real deployment state locks and native Run ownership, offline."""
from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

import pytest

from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.runtime.cli_admission import (
    CliDeploymentAdmissionError,
    bind_cli_startup,
    cli_state_admission,
)
from llm_loop.runtime.cli_deployment_identity import StartupArtifactIdentity
from llm_loop.runtime.service_control import (
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
    _target_idle_state,
)


def _setup(data: Path):
    data = data.resolve()
    code = data.parent / "immutable-release"
    desired = ManagedServiceDeployment(
        schema="lfl.managed-service-deployment/v2", deployment_id="cli-admission",
        generation=1, git_head="a" * 40, code_root=str(code),
        runtime_root=str(data.parent), data_dir=str(data),
        webui_artifact_sha256="c" * 64, artifact_kind="source_checkout",
    )
    startup = StartupArtifactIdentity(42, "source_checkout", str(code / "src/llm_loop/__init__.py"),
                                      "/venv/bin/python", code_root=str(code), git_head=desired.git_head)
    store = ManagedServiceDeploymentStore(data)
    store.compare_and_swap(desired, expected_generation=0)
    return store, desired, startup, bind_cli_startup(data, startup)


def test_same_sha_new_generation_invalidates_startup(tmp_path):
    store, desired, startup, binding = _setup(tmp_path / "cli-domain")
    with cli_state_admission(binding):
        pass
    store.compare_and_swap(replace(desired, generation=2), expected_generation=1)
    with pytest.raises(CliDeploymentAdmissionError, match="deployment_generation_changed"), cli_state_admission(binding):
        pytest.fail("old generation must not be admitted")
    with cli_state_admission(bind_cli_startup(store.data_dir, startup)):
        pass


def test_independent_domain_then_first_publish(tmp_path):
    data = tmp_path / "independent-domain"
    startup = StartupArtifactIdentity(42, "unknown", "/dev/package", "/dev/python")
    binding = bind_cli_startup(data, startup)
    with cli_state_admission(binding):
        pass
    _setup(data)
    with pytest.raises(CliDeploymentAdmissionError, match="deployment_generation_changed"), cli_state_admission(binding):
        pytest.fail("new deployment invalidates unmanaged binding")


def test_restart_acceptance_serializes_with_admission(tmp_path):
    store, desired, _startup, binding = _setup(tmp_path / "cli-domain")
    entered, finished = threading.Event(), threading.Event()
    errors = []

    def accept():
        entered.set()
        try:
            store.accept_restart(target="all", expected_generation=desired.generation,
                                 requester_session_id="test")
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=accept)
    with cli_state_admission(binding):
        thread.start()
        assert entered.wait(2)
        assert not finished.wait(0.1), "restart must not establish barrier mid-admission"
    thread.join(5)
    assert finished.is_set() and not errors
    with pytest.raises(CliDeploymentAdmissionError, match="service_restart_barrier"), cli_state_admission(binding):
        pytest.fail("new run must not cross accepted restart")


def test_real_run_lease_survives_publish_and_stale_next_run_is_refused(build_test_engine, monkeypatch):
    from llm_loop.llm.client import LLMResponse, StreamDelta

    engine, fake = build_test_engine([])
    store, desired, _startup, binding = _setup(Path(engine.settings.data_dir))
    engine._cli_admission_binding = binding
    wake_calls = []
    monkeypatch.setattr(engine, "rearm_wake_grants", lambda sid, _ingress: wake_calls.append(sid), raising=False)
    first_sid, second_sid = engine.session.create(), engine.session.create()

    def stream(**_kwargs):
        yield StreamDelta(text="A")
        yield StreamDelta(text="B")
        return LLMResponse(content="AB", tool_calls=[], provider="fake")

    fake.chat_stream = stream
    first = engine.run_stream(first_sid, "first", ingress=issue_ingress("cli"))
    try:
        assert next(first).text == "A"
        # Publication can advance while an admitted Run continues. No long
        # state lock is held during the provider stream.
        store.compare_and_swap(replace(desired, generation=2), expected_generation=1)
        assert _target_idle_state(target="web", runtime_root=desired.runtime_root,
                                  data_dir=store.data_dir)[0] == "confirmed_busy"
        with pytest.raises(CliDeploymentAdmissionError, match="deployment_generation_changed"):
            engine.run(second_sid, "must not be sent", ingress=issue_ingress("cli"))
        assert not engine.session.load(second_sid).messages
        assert wake_calls == [first_sid]
        assert next(first).text == "B"
        with pytest.raises(StopIteration) as stopped:
            next(first)
        assert stopped.value.value.final_answer == "AB"
    finally:
        first.close()
    assert _target_idle_state(target="web", runtime_root=desired.runtime_root,
                              data_dir=store.data_dir)[0] == "confirmed_idle"


def test_wrong_root_or_unreadable_record_refuses_before_body(tmp_path):
    store, _desired, startup, _binding = _setup(tmp_path / "cli-domain")
    wrong = bind_cli_startup(store.data_dir, replace(startup, code_root="/other"))
    with pytest.raises(CliDeploymentAdmissionError, match="code_root_mismatch"), cli_state_admission(wrong):
        pytest.fail("wrong root")
    store.path.write_text("invalid", encoding="utf-8")
    with pytest.raises(CliDeploymentAdmissionError, match="deployment_record_unreadable"):
        bind_cli_startup(store.data_dir, startup)
