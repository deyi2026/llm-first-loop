"""Verified workspace artifact hydration endpoint tests (provider-free).

CONTRACT.md "Required verification" 第 4 条的 App 侧前置：认证 scope 归属、
SHA256 readback、越权/伪造统一 404 防枚举、blob 篡改 409。
"""
from __future__ import annotations

import hashlib
import pathlib
import tempfile

from fastapi.testclient import TestClient

from llm_loop.web import build_app
from llm_loop.web.routes import _current_attachment_workspace_scope
from llm_loop.workspace.artifacts import ArtifactError, WorkspaceArtifactStore


def _client(build_test_engine):
    engine, _ = build_test_engine([])
    return TestClient(build_app(engine=engine)), engine


def _record(store, scope, path_suffix, data, tag):
    return store.create(
        workspace_scope=scope,
        canonical_path=f"{scope}/{path_suffix}",
        data=data,
        owner_session_id=f"s-{tag}",
        execution_id=f"e-{tag}",
        tool_call_id=f"t-{tag}",
        tool_name="pytest",
        effect_kind="test",
    )


def test_positive_cross_scope_and_malformed(build_test_engine):
    client, engine = _client(build_test_engine)
    scope = _current_attachment_workspace_scope(engine)
    store = WorkspaceArtifactStore(
        getattr(getattr(engine, "settings", None), "data_dir", "./data")
    )
    data = b"native-bridge-fixture-bytes"
    record = _record(store, scope, "fixtures/native.bin", data, "a")

    ok = client.get(f"/api/v1/artifacts/{record.artifact_id}")
    assert ok.status_code == 200
    assert ok.content == data
    assert ok.headers["x-artifact-sha256"] == hashlib.sha256(data).hexdigest()
    assert ok.headers["x-artifact-ref"] == record.ref
    assert ok.headers["x-artifact-size-bytes"] == str(len(data))
    assert ok.headers["x-artifact-relative-path"].endswith("native.bin")

    # 伪造与非法 id 统一 404
    assert client.get("/api/v1/artifacts/" + "0" * 32).status_code == 404
    assert client.get("/api/v1/artifacts/not-hex-at-all").status_code == 404
    assert client.get("/api/v1/artifacts/" + "a" * 33).status_code == 404

    # 跨 workspace 归属：另一 scope 的 artifact 不可见（防枚举 404）
    with tempfile.TemporaryDirectory() as other_root:
        other_scope = str(pathlib.Path(other_root).resolve())
        other = _record(store, other_scope, "x.bin", b"other-workspace", "b")
        assert client.get(f"/api/v1/artifacts/{other.artifact_id}").status_code == 404


def test_corrupt_blob_maps_to_409(build_test_engine, monkeypatch):
    client, engine = _client(build_test_engine)
    scope = _current_attachment_workspace_scope(engine)
    store = WorkspaceArtifactStore(
        getattr(getattr(engine, "settings", None), "data_dir", "./data")
    )
    record = _record(store, scope, "fixtures/corrupt.bin", b"will-be-corrupt", "c")

    def _raise(self, rec):
        raise ArtifactError("artifact blob 完整性校验失败。")

    monkeypatch.setattr(WorkspaceArtifactStore, "_read_blob_verified", _raise)
    res = client.get(f"/api/v1/artifacts/{record.artifact_id}")
    assert res.status_code == 409
    assert res.json()["error"] == "artifact_integrity_failure"
