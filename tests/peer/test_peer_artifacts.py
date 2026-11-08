"""产物仓库：内容寻址、ref 校验、digest 不符 fail-closed。"""
from __future__ import annotations

import hashlib

import pytest

from llm_loop.peer.artifacts import ArtifactStore
from llm_loop.peer.errors import PeerError


@pytest.fixture()
def store(tmp_path):
    return ArtifactStore(tmp_path / "artifacts")


def test_put_then_read_roundtrip(store):
    data = b"hello\n"
    desc = store.put(data, media_type="text/plain")
    assert desc["ref"] == "artifact://v1/" + hashlib.sha256(data).hexdigest()
    assert desc["sha256"] == hashlib.sha256(data).hexdigest()
    assert desc["bytes"] == len(data)
    assert store.read(desc["ref"]) == data


def test_put_is_content_addressed_and_idempotent(store):
    a = store.put(b"same")
    b = store.put(b"same")
    assert a == b
    files = list((store.root / "objects").rglob("*"))
    assert len([p for p in files if p.is_file()]) == 1


def test_artifact_file_mode_is_0600(store):
    desc = store.put(b"secret-ish")
    path = store.root / "objects" / desc["sha256"][:2] / desc["sha256"]
    assert (path.stat().st_mode & 0o777) == 0o600


def test_read_missing_is_artifact_missing(store):
    ref = "artifact://v1/" + "a" * 64
    with pytest.raises(PeerError) as err:
        store.read(ref)
    assert err.value.reason_code == "artifact_missing"


def test_tampered_content_is_digest_mismatch(store):
    desc = store.put(b"original")
    path = store.root / "objects" / desc["sha256"][:2] / desc["sha256"]
    path.chmod(0o600)
    path.write_bytes(b"tampered")
    with pytest.raises(PeerError) as err:
        store.read(desc["ref"])
    assert err.value.reason_code == "artifact_digest_mismatch"


@pytest.mark.parametrize(
    "ref",
    [
        "artifact://v1/short",
        "artifact://v2/" + "a" * 64,
        "artifact://v1/../../etc/passwd",
        "artifact://v1/" + "z" * 64,
        "",
    ],
)
def test_malformed_refs_rejected(store, ref):
    with pytest.raises(PeerError) as err:
        store.read(ref)
    assert err.value.reason_code == "params_schema_invalid"


def test_oversize_rejected(store):
    small = ArtifactStore(store.root, max_bytes=4)
    with pytest.raises(PeerError) as err:
        small.put(b"12345")
    assert err.value.reason_code == "params_schema_invalid"
