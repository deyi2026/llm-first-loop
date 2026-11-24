"""Live identity is lock-backed, not inferred from a stale PID file."""
from __future__ import annotations

import os
from dataclasses import replace

from llm_loop.runtime.cli_admission import bind_cli_startup
from llm_loop.runtime.cli_deployment_identity import StartupArtifactIdentity
from llm_loop.runtime.cli_processes import cli_process_view, register_cli_process
from llm_loop.runtime.service_control import ManagedServiceDeployment, ManagedServiceDeploymentStore


def test_live_cli_process_view_and_generation_drift(tmp_path):
    data = tmp_path / "cli-domain"
    root = tmp_path / "release"
    desired = ManagedServiceDeployment(
        schema="lfl.managed-service-deployment/v2", deployment_id="process-view", generation=1,
        git_head="a" * 40, code_root=str(root), runtime_root=str(tmp_path), data_dir=str(data),
        artifact_kind="source_checkout", webui_artifact_sha256="c" * 64,
    )
    startup = StartupArtifactIdentity(os.getpid(), "source_checkout", str(root / "src/llm_loop/__init__.py"),
                                      "/python", code_root=str(root), git_head=desired.git_head)
    store = ManagedServiceDeploymentStore(data)
    store.compare_and_swap(desired, expected_generation=0)
    binding = bind_cli_startup(data, startup)
    registry = data / "runtime/cli-processes"
    assert cli_process_view(data, desired)["state"] == "not_running"
    assert not registry.exists()
    with register_cli_process(binding):
        view = cli_process_view(data, desired)
        assert view["state"] == "identity_matches_target"
        assert view["processes"][0]["pid"] == os.getpid()
        assert view["processes"][0]["generation"] == 1
        record = next(registry.iterdir())
        before = record.read_bytes()
        advanced = replace(desired, generation=2)
        store.compare_and_swap(advanced, expected_generation=1)
        view = cli_process_view(data, advanced)
        assert view["state"] == "update_required"
        assert view["processes"][0]["reason"] == "deployment_generation_changed"
        assert record.read_bytes() == before
    assert not list(registry.iterdir())
    stale = registry / "cli-stale.json"
    stale.write_bytes(before)
    assert cli_process_view(data, advanced)["state"] == "not_running"
    assert stale.read_bytes() == before
