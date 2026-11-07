"""闸2/闸3：kind、租约生命周期、并发配额、路径包含、params 形状。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from llm_loop.peer.errors import PeerError
from llm_loop.peer.kinds import get_kind
from llm_loop.peer.models import GrantRecord, iso, utcnow
from llm_loop.peer.policy import (
    evaluate,
    is_sensitive_path,
    params_paths,
    path_within,
    require_path_allowed,
    require_supervision,
    validate_params,
)


def grant(**overrides) -> GrantRecord:
    base = dict(
        grant_id="grant-1",
        node_id="deepin-01",
        issued_by={"ingress": "feishu", "human": "lfl"},
        issued_at=iso(utcnow()),
        expires_at=iso(utcnow() + timedelta(hours=1)),
        state="active",
        allowed_kinds=("fs.read", "fs.list"),
        allowed_paths=("/srv/allowed",),
        max_concurrency=2,
        max_tasks_total=10,
    )
    base.update(overrides)
    return GrantRecord(**base)


def test_evaluate_happy_path(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    g = grant(allowed_paths=(str(root),))
    spec = evaluate(kind="fs.read", params={"path": str(root / "a.txt")}, grant=g)
    assert spec.kind == "fs.read"


def test_kind_not_in_grant_denied():
    with pytest.raises(PeerError) as err:
        evaluate(kind="fs.list", params={"path": "/srv/allowed"}, grant=grant(allowed_kinds=("fs.read",)))
    assert err.value.reason_code == "policy_task_kind_not_allowed"


def test_unknown_kind_denied():
    with pytest.raises(PeerError) as err:
        evaluate(kind="gpu.mine", params={}, grant=grant(allowed_kinds=("gpu.mine",)))
    assert err.value.reason_code == "policy_task_kind_not_allowed"


def test_revoked_beats_expired():
    g = grant(state="revoked", expires_at=iso(utcnow() - timedelta(hours=1)))
    with pytest.raises(PeerError) as err:
        evaluate(kind="fs.read", params={"path": "/srv/allowed/a"}, grant=g)
    assert err.value.reason_code == "grant_revoked"


def test_expired_denied():
    g = grant(expires_at=iso(utcnow() - timedelta(seconds=1)))
    with pytest.raises(PeerError) as err:
        evaluate(kind="fs.read", params={"path": "/srv/allowed/a"}, grant=g)
    assert err.value.reason_code == "grant_expired"


def test_exhausted_denied():
    with pytest.raises(PeerError) as err:
        evaluate(kind="fs.read", params={"path": "/srv/allowed/a"}, grant=grant(tasks_used=10))
    assert err.value.reason_code == "grant_exhausted"


def test_unbounded_grant_denied():
    with pytest.raises(PeerError) as err:
        evaluate(kind="fs.read", params={"path": "/srv/allowed/a"}, grant=grant(expires_at=""))
    assert err.value.reason_code == "grant_unbounded"
    with pytest.raises(PeerError) as err:
        evaluate(kind="fs.read", params={"path": "/srv/allowed/a"}, grant=grant(max_tasks_total=0))
    assert err.value.reason_code == "grant_unbounded"


def test_concurrency_quota_denied():
    with pytest.raises(PeerError) as err:
        evaluate(kind="fs.read", params={"path": "/srv/allowed/a"}, grant=grant(), running_tasks=2)
    assert err.value.reason_code == "quota_concurrency_exceeded"


def test_supervised_only_kind_denied_when_unattended():
    spec = get_kind("fs.write")
    assert spec is not None and spec.supervised_only
    with pytest.raises(PeerError) as err:
        require_supervision(spec, supervised=False)
    assert err.value.reason_code == "requires_supervised_execution"


def test_path_escape_rejected(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    for bad in (str(root / ".." / "outside.txt"), str(outside), "relative/path", ""):
        with pytest.raises(PeerError) as err:
            require_path_allowed(bad, (str(root),))
        assert err.value.reason_code == "path_outside_allowed_paths"


def test_symlink_escape_rejected(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    secret = tmp_path / "elsewhere.txt"
    secret.write_text("x")
    link = root / "link.txt"
    link.symlink_to(secret)
    with pytest.raises(PeerError) as err:
        require_path_allowed(str(link), (str(root),))
    assert err.value.reason_code == "path_outside_allowed_paths"


def test_sensitive_paths_rejected_even_if_allowed(tmp_path):
    secrets = tmp_path / "work" / "data" / "peer" / "secrets"
    secrets.mkdir(parents=True)
    target = secrets / "node-a.secret"
    target.write_text("k")
    assert is_sensitive_path(str(target))
    with pytest.raises(PeerError) as err:
        require_path_allowed(str(target), (str(tmp_path),))
    assert err.value.reason_code == "path_outside_allowed_paths"


def test_path_within_root_itself_is_allowed(tmp_path):
    assert path_within(str(tmp_path), (str(tmp_path),)) is True


def test_params_shape_errors():
    cases = [
        ("fs.read", {"path": "/srv/allowed/a", "max_bytes": 2_000_000}),
        ("fs.read", {"path": "/srv/allowed/a", "max_bytes": True}),
        ("fs.read", {"path": "/srv/allowed/a", "unexpected": 1}),
        ("fs.read", {}),
        ("fs.list", {"path": "/srv/allowed", "depth": 4}),
        ("shell.exec", {"argv": [], "cwd": "/srv/allowed"}),
        ("shell.exec", {"argv": ["ls"], "timeout_s": 121}),
        ("desktop.click", {"x": 1, "y": 2}),
        ("desktop.focus_probe", {"x": 1}),
    ]
    for kind, params in cases:
        with pytest.raises(PeerError) as err:
            validate_params(kind, params)
        assert err.value.reason_code == "params_schema_invalid", (kind, params)


def test_params_paths_are_kind_specific():
    assert params_paths("fs.read", {"path": "/a"}) == ("/a",)
    assert params_paths("shell.exec", {"argv": ["ls"], "cwd": "/a"}) == ("/a",)
    assert params_paths("desktop.screenshot", {"display": ":0"}) == ()


def test_common_prefix_trap_not_accepted(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    sibling = tmp_path / "allowed-evil"
    sibling.mkdir()
    assert path_within(str(sibling / "x"), (str(root),)) is False
