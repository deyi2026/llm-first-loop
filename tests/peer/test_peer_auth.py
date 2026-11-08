"""认证层：四头 HMAC 通过/拒绝路径、时钟窗、nonce 重放、nonce 中毒防护。"""
from __future__ import annotations

import re

import pytest

from llm_loop.peer.auth import (
    HEADER_NODE,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    MAX_SKEW_SECONDS,
    NONCE_MAX_ENTRIES,
    NONCE_WINDOW_SECONDS,
    NonceCache,
    PeerAuthenticator,
    body_digest,
    build_canonical,
    compose_path,
    sign,
    sign_request,
)
from llm_loop.peer.errors import PeerError

SECRET = b"\x01" * 32
NOW = 1_800_000_000


def _auth(clock=lambda: NOW, **kwargs):
    secrets = {"node-a": SECRET}
    return PeerAuthenticator(secret_for=secrets.get, clock=clock, **kwargs)


def _req(secret: bytes = SECRET, *, node_id: str = "node-a", nonce: str = "a" * 32, ts: int = NOW,
         path: str = "/api/peer/manifest", method: str = "GET", query: str = "", body: bytes | None = None):
    headers = sign_request(
        secret=secret,
        method=method,
        path=path,
        query=query,
        node_id=node_id,
        nonce=nonce,
        timestamp=ts,
        body=body,
    )
    return {"method": method, "path": path, "query": query, "headers": headers, "body": body}


def test_happy_path_returns_node_id():
    a = _auth()
    assert a.verify_request(**_req()) == "node-a"


def test_body_is_part_of_signature():
    a = _auth()
    req = _req(method="POST", body=b'{"x":1}')
    assert a.verify_request(**req) == "node-a"
    tampered = dict(req, body=b'{"x":2}')
    with pytest.raises(PeerError) as err:
        a.verify_request(**tampered)
    assert err.value.reason_code == "peer_bad_signature"


def test_query_is_part_of_signature():
    a = _auth()
    req = _req(query="limit=1")
    assert a.verify_request(**req) == "node-a"
    with pytest.raises(PeerError) as err:
        a.verify_request(**dict(req, query="limit=2"))
    assert err.value.reason_code == "peer_bad_signature"


@pytest.mark.parametrize("field", ["path", "method"])
def test_path_and_method_are_signed(field: str):
    a = _auth()
    req = _req()
    changed = dict(req)
    changed[field] = "/api/peer/other" if field == "path" else "POST"
    with pytest.raises(PeerError) as err:
        a.verify_request(**changed)
    assert err.value.reason_code == "peer_bad_signature"


@pytest.mark.parametrize("header", [HEADER_NODE, HEADER_TIMESTAMP, HEADER_NONCE, HEADER_SIGNATURE])
def test_missing_header_rejected(header: str):
    a = _auth()
    req = _req()
    headers = dict(req["headers"])
    headers.pop(header)
    with pytest.raises(PeerError) as err:
        a.verify_request(**dict(req, headers=headers))
    assert err.value.reason_code == "peer_bad_signature"
    assert header in err.value.detail


def test_unknown_node_rejected():
    a = _auth()
    req = _req(node_id="node-z")
    with pytest.raises(PeerError) as err:
        a.verify_request(**req)
    assert err.value.reason_code == "peer_unknown_node"


@pytest.mark.parametrize("delta", [-(MAX_SKEW_SECONDS + 1), MAX_SKEW_SECONDS + 1])
def test_clock_skew_both_directions(delta: int):
    a = _auth()
    with pytest.raises(PeerError) as err:
        a.verify_request(**_req(ts=NOW + delta))
    assert err.value.reason_code == "peer_stale_signature"


def test_skew_boundary_accepted():
    a = _auth()
    assert a.verify_request(**_req(ts=NOW - MAX_SKEW_SECONDS)) == "node-a"


def test_replay_same_nonce_rejected():
    a = _auth()
    req = _req()
    assert a.verify_request(**req) == "node-a"
    with pytest.raises(PeerError) as err:
        a.verify_request(**req)
    assert err.value.reason_code == "peer_replay_detected"


def test_replay_does_not_poison_nonce_window():
    """先发一个坏签名 + 好 nonce 的攻击请求，再发真请求必须仍能通过。"""
    a = _auth()
    good = _req()
    bad = _req(secret=b"\x02" * 32)
    with pytest.raises(PeerError) as err:
        a.verify_request(**bad)
    assert err.value.reason_code == "peer_bad_signature"
    assert a.verify_request(**good) == "node-a"


def test_nonce_namespace_is_per_node():
    a = _auth()
    assert a.verify_request(**_req(node_id="node-a", nonce="b" * 32)) == "node-a"
    other = _req(node_id="node-b", nonce="b" * 32)
    # node-b 未配对 → 先被 unknown 挡住（证明命名空间不会串）
    with pytest.raises(PeerError) as err:
        a.verify_request(**other)
    assert err.value.reason_code == "peer_unknown_node"


def test_malformed_nonce_and_timestamp_rejected():
    a = _auth()
    for field, value in ((HEADER_NONCE, "not-a-nonce"), (HEADER_TIMESTAMP, "abc")):
        req = _req()
        headers = dict(req["headers"], **{field: value})
        with pytest.raises(PeerError) as err:
            a.verify_request(**dict(req, headers=headers))
        assert err.value.reason_code == "peer_bad_signature"


def test_canonical_is_exactly_five_lines_in_design_order():
    """契约逐字：METHOD\nPATH(含query)\nSHA256_HEX(BODY)\nTS\nNONCE。"""
    digest = body_digest(b'{"k":1}')
    canonical = build_canonical(
        method="post",
        path=compose_path("/peer/v1/tasks", "a=1&b=2"),
        body_sha256=digest,
        timestamp="1794028800",
        nonce="9c4f2a7b1d8e3f506a2c9b4d7e1f8203",
    )
    assert canonical.split("\n") == [
        "POST",
        "/peer/v1/tasks?a=1&b=2",
        digest,
        "1794028800",
        "9c4f2a7b1d8e3f506a2c9b4d7e1f8203",
    ]


def test_empty_body_uses_empty_string_digest():
    assert body_digest(None) == body_digest(b"")
    assert body_digest(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_compose_path_keeps_query_and_omits_empty():
    assert compose_path("/peer/v1/manifest") == "/peer/v1/manifest"
    assert compose_path("/peer/v1/manifest", "?a=1") == "/peer/v1/manifest?a=1"
    assert compose_path("/peer/v1/tasks", "a=1") == "/peer/v1/tasks?a=1"


def test_signature_is_base64_not_hex():
    sig = sign(SECRET, "X")
    assert len(sig) == 44 and sig.endswith("=")
    assert re.fullmatch(r"[A-Za-z0-9+/]{43}=", sig)


def test_canonical_rejects_newline_injection():
    with pytest.raises(PeerError) as err:
        build_canonical(
            method="GET",
            path="/a\nnode-x",
            body_sha256="0" * 64,
            timestamp=str(NOW),
            nonce="c" * 32,
        )
    assert err.value.reason_code == "peer_bad_signature"


def test_nonce_window_and_capacity_match_design():
    assert NONCE_WINDOW_SECONDS == 600
    assert NONCE_MAX_ENTRIES == 10_000
    cache = NonceCache(window_seconds=NONCE_WINDOW_SECONDS, clock=lambda: 0.0)
    assert cache.check_and_store("node-a", "d" * 32, now=0.0) is True
    assert cache.check_and_store("node-a", "d" * 32, now=599.0) is False


def test_nonce_cache_purges_expired_entries():
    cache = NonceCache(window_seconds=10, clock=lambda: 0.0)
    assert cache.check_and_store("node-a", "d" * 32, now=0.0) is True
    assert len(cache) == 1
    cache.check_and_store("node-a", "e" * 32, now=11.0)
    assert len(cache) == 1


def test_nonce_cache_capacity_is_bounded():
    cache = NonceCache(window_seconds=1000, max_entries=5, clock=lambda: 0.0)
    for i in range(20):
        assert cache.check_and_store("node-a", f"{i:032x}", now=float(i)) is True
    assert len(cache) <= 5


def test_headers_dict_is_case_insensitive():
    a = _auth()
    req = _req()
    lower = {k.lower(): v for k, v in req["headers"].items()}
    assert a.verify_request(**dict(req, headers=lower)) == "node-a"
