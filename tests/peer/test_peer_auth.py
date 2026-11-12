"""认证层：四头 HMAC 通过/拒绝路径、时钟窗、nonce 重放、nonce 中毒防护、持久防重放。"""

from __future__ import annotations

import hashlib
import os
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
NEW_SECRET = b"\x0f" * 32
NOW = 1_800_000_000


def _auth(clock=lambda: NOW, **kwargs):
    secrets = {"node-a": SECRET}
    return PeerAuthenticator(secret_for=secrets.get, clock=clock, **kwargs)


def _req(
    secret: bytes = SECRET,
    *,
    node_id: str = "node-a",
    nonce: str = "a" * 32,
    ts: int = NOW,
    path: str = "/api/peer/manifest",
    method: str = "GET",
    query: str = "",
    body: bytes | None = None,
):
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
    assert body_digest(b"") == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


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


# ---- 持久防重放（设计 §6.5 / A09：分桶、窗口内结构性永不淘汰、换钥过渡）----
# 契约依据（逐字取自设计书，非实现同源）：
# - R04/A09: 重启及共享状态的多个接收进程统一拒绝已接受的同一 nonce，不以容量淘汰放行。
# - §6.5: 按「节点+密钥代际+时间窗」三级分桶；窗口整体过期后原子清理整桶，
#   窗口内记录结构性永不淘汰；换钥时旧代际桶保留至其签名窗（含时钟偏差）完全结束。
# - §6.5: 每个已验签请求 nonce「先持久、后响应」，每次请求一次持久写（锁+fsync）；
#   验证垃圾签名不能消耗持久槽位；存储故障不放行。


def _persistent_auth(persist, clock=lambda: NOW, secret_for=None):
    return PeerAuthenticator(
        secret_for=secret_for or {"node-a": SECRET}.get,
        nonce_cache=NonceCache(persist_dir=persist, clock=clock),
        clock=clock,
    )


def test_replay_rejected_across_process_restart(tmp_path):
    """① 进程重启（重新实例化、持久文件保留）后，时间窗内同一 nonce 重放被拒。"""
    persist = tmp_path / "peer-store"
    a = _persistent_auth(persist)
    assert a.verify_request(**_req()) == "node-a"
    b = _persistent_auth(persist)  # “重启”：内存态全丢，仅磁盘记录保留
    with pytest.raises(PeerError) as err:
        b.verify_request(**_req())
    assert err.value.reason_code == "peer_replay_detected"
    # 持久记录覆盖完整签名有效窗（±300s 偏差）：窗内稍后重放仍被拒
    c = _persistent_auth(persist, clock=lambda: NOW + 299)
    with pytest.raises(PeerError) as err:
        c.verify_request(**_req())
    assert err.value.reason_code == "peer_replay_detected"
    # 拒绝是重放特有，不是存储整体不可用：新 nonce 正常通过
    assert c.verify_request(**_req(nonce="c" * 32)) == "node-a"


def test_persistent_buckets_by_window_and_generation_no_eviction(tmp_path):
    """② 按 节点+代际+时间窗 分文件；窗口内结构性永不淘汰（不受 max_entries 影响）。"""
    persist = tmp_path / "peer-store"
    cache = NonceCache(
        persist_dir=persist,
        max_entries=2,  # 故意配一个远低于流量的容量：持久路径不允许因此放行
        window_seconds=NONCE_WINDOW_SECONDS,
        clock=lambda: float(NOW),
    )
    for i in range(20):
        assert cache.check_and_store("node-a", f"{i:032x}", now=float(NOW)) is True
    assert cache.stats["appends"] == 20  # 每次接受恰好一次持久写（成本可测量）
    for i in range(20):  # 窗口内重放全部被拒——不因容量淘汰而放行
        assert cache.check_and_store("node-a", f"{i:032x}", now=float(NOW + 60)) is False
    # 同一 nonce 不同密钥代际分桶：两代各自首次都应接受
    assert cache.check_and_store("node-a", "f" * 32, now=float(NOW), key_generation="k1") is True
    assert cache.check_and_store("node-a", "f" * 32, now=float(NOW), key_generation="k2") is True
    # 桶文件按时间窗组织：NOW 恰为窗口边界，索引 = NOW // 600
    window_file = persist / "nonce" / "node-a" / "default" / f"{NOW // NONCE_WINDOW_SECONDS}.jsonl"
    assert window_file.is_file()
    assert (persist / "nonce" / "node-a" / "k1").is_dir()
    assert (persist / "nonce" / "node-a" / "k2").is_dir()
    # 节点隔离：不同节点各自分桶
    assert cache.check_and_store("node-b", "f" * 32, now=float(NOW + 60)) is True
    assert (persist / "nonce" / "node-b" / "default").is_dir()
    # 跨时间窗重放：上一窗末尾接受、下一窗开头重放必须检出（持久窗 ≥ 签名窗+偏差）
    assert cache.check_and_store("node-c", "a" * 32, now=NOW + 599.0) is True
    assert cache.check_and_store("node-c", "a" * 32, now=NOW + 601.0) is False


def test_persistent_bucket_cleanup_whole_window_after_expiry(tmp_path):
    """② 窗口整体过期后原子清理整桶；有效期内不清理（换钥旧代桶同理保留到窗口结束）。"""
    persist = tmp_path / "peer-store"
    cache = NonceCache(persist_dir=persist, window_seconds=10, bucket_seconds=10, clock=lambda: 0.0)
    assert cache.check_and_store("node-a", "f" * 32, now=0.0, key_generation="g1") is True
    bucket = persist / "nonce" / "node-a" / "g1" / "0.jsonl"
    assert bucket.is_file()
    cache.cleanup(now=19.0)  # (0+1)*10+10=20 > 19：签名窗尚未整体结束，不清理
    assert bucket.is_file()
    removed = cache.cleanup(now=20.0)
    assert removed >= 1
    assert not bucket.exists()
    assert cache.check_and_store("node-a", "f" * 32, now=20.0, key_generation="g1") is True


def test_key_rotation_old_generation_transition_and_replay(tmp_path):
    """③ 换钥过渡双代并验；重启后旧窗内旧钥签名重放仍被拒（A09 扩展）。"""
    persist = tmp_path / "peer-store"

    def rotating(clock=lambda: NOW):
        return PeerAuthenticator(
            secret_for={"node-a": NEW_SECRET}.get,
            previous_secret_for={"node-a": SECRET}.get,
            nonce_cache=NonceCache(persist_dir=persist, clock=clock),
            clock=clock,
        )

    a = rotating()
    old_req = _req(secret=SECRET)  # 旧代密钥签名
    assert a.verify_request(**old_req) == "node-a"
    assert a.verify_request(**_req(secret=NEW_SECRET, nonce="b" * 32)) == "node-a"
    # 旧代与新代按密钥代际分桶（节点+代际+时间窗三级）
    old_gen = hashlib.sha256(SECRET).hexdigest()[:16]
    new_gen = hashlib.sha256(NEW_SECRET).hexdigest()[:16]
    assert old_gen != new_gen
    assert (persist / "nonce" / "node-a" / old_gen).is_dir()
    assert (persist / "nonce" / "node-a" / new_gen).is_dir()
    # “重启”后旧窗内旧钥签名重放仍被拒
    b = rotating(clock=lambda: NOW + 299)
    with pytest.raises(PeerError) as err:
        b.verify_request(**old_req)
    assert err.value.reason_code == "peer_replay_detected"
    # 节点仅在旧代密钥可查（当前钥未配置）时仍视为已知节点，按旧代验签
    only_old = PeerAuthenticator(
        secret_for=lambda _n: None,
        previous_secret_for={"node-a": SECRET}.get,
        nonce_cache=NonceCache(persist_dir=persist, clock=lambda: NOW + 299),
        clock=lambda: NOW + 299,
    )
    assert only_old.verify_request(**_req(secret=SECRET, nonce="d" * 32)) == "node-a"


def test_bad_signature_does_not_consume_persistent_slot(tmp_path):
    """§6.5：验证垃圾签名不能消耗持久槽位（先验签后落账，持久路径同样成立）。"""
    persist = tmp_path / "peer-store"
    cache = NonceCache(persist_dir=persist, clock=lambda: NOW)
    a = PeerAuthenticator(secret_for={"node-a": SECRET}.get, nonce_cache=cache, clock=lambda: NOW)
    with pytest.raises(PeerError) as err:
        a.verify_request(**_req(secret=b"\x02" * 32))
    assert err.value.reason_code == "peer_bad_signature"
    assert cache.stats["appends"] == 0  # 坏签名未写任何持久记录
    assert a.verify_request(**_req()) == "node-a"
    assert cache.stats["appends"] == 1


def test_persistent_storage_failure_fails_closed(tmp_path, monkeypatch):
    """A09：存储故障不放行——fsync 失败抛 PeerError，绝不静默当作已接受。"""
    persist = tmp_path / "peer-store"
    cache = NonceCache(persist_dir=persist, clock=lambda: NOW)
    a = PeerAuthenticator(secret_for={"node-a": SECRET}.get, nonce_cache=cache, clock=lambda: NOW)
    assert a.verify_request(**_req()) == "node-a"

    def broken_fsync(fd):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    with pytest.raises(PeerError) as err:
        a.verify_request(**_req(nonce="c" * 32))
    assert err.value.reason_code == "executor_internal_error"
    monkeypatch.undo()
    # 故障期间未给出“已接受”响应；恢复后该 nonce 不会被第二次接受（先持久后响应的残余是拒绝）
    with pytest.raises(PeerError) as err:
        a.verify_request(**_req(nonce="c" * 32))
    assert err.value.reason_code == "peer_replay_detected"


def test_persistent_nonce_rejects_replay_at_inclusive_signature_window_endpoint(tmp_path):
    now = [float(NOW)]
    cache = NonceCache(persist_dir=tmp_path, clock=lambda: now[0])
    auth = PeerAuthenticator(
        secret_for={"node-a": SECRET}.get,
        nonce_cache=cache,
        clock=lambda: now[0],
    )
    request = _req(ts=NOW + MAX_SKEW_SECONDS)

    assert auth.verify_request(**request) == "node-a"
    # The signature remains valid at the inclusive +MAX_SKEW endpoint. The
    # nonce must therefore remain protected when its nominal 600s window ends.
    now[0] = float(NOW + 2 * MAX_SKEW_SECONDS)
    restarted = PeerAuthenticator(
        secret_for={"node-a": SECRET}.get,
        nonce_cache=NonceCache(persist_dir=tmp_path, clock=lambda: now[0]),
        clock=lambda: now[0],
    )
    with pytest.raises(PeerError) as err:
        restarted.verify_request(**request)
    assert err.value.reason_code == "peer_replay_detected"


def test_persistent_nonce_fails_closed_on_clock_rollback_within_signature_window(tmp_path):
    now = [float(NOW + MAX_SKEW_SECONDS)]
    cache = NonceCache(persist_dir=tmp_path, clock=lambda: now[0])
    auth = PeerAuthenticator(
        secret_for={"node-a": SECRET}.get,
        nonce_cache=cache,
        clock=lambda: now[0],
    )
    request = _req(ts=NOW)

    assert auth.verify_request(**request) == "node-a"
    # Rolling back by 600s makes the same signed request valid at the opposite
    # inclusive endpoint. A persistent high-water mark must fail closed.
    now[0] = float(NOW - MAX_SKEW_SECONDS)
    restarted = PeerAuthenticator(
        secret_for={"node-a": SECRET}.get,
        nonce_cache=NonceCache(persist_dir=tmp_path, clock=lambda: now[0]),
        clock=lambda: now[0],
    )
    with pytest.raises(PeerError) as err:
        restarted.verify_request(**request)
    assert err.value.reason_code == "executor_internal_error"
    assert "clock rollback" in err.value.detail.lower()


def test_persistent_nonce_cleanup_cannot_erase_clock_rollback_evidence(tmp_path):
    now = [float(NOW)]
    cache = NonceCache(persist_dir=tmp_path, clock=lambda: now[0])
    auth = PeerAuthenticator(
        secret_for={"node-a": SECRET}.get,
        nonce_cache=cache,
        clock=lambda: now[0],
    )
    request = _req(ts=NOW + MAX_SKEW_SECONDS)

    assert auth.verify_request(**request) == "node-a"
    # A forward jump expires and removes the bucket. The durable clock
    # high-water mark must survive cleanup so a later rollback cannot revive
    # a still-valid signature at the old endpoint.
    cache.cleanup(now=float(NOW + 4 * MAX_SKEW_SECONDS))
    now[0] = float(NOW + 2 * MAX_SKEW_SECONDS)
    restarted = PeerAuthenticator(
        secret_for={"node-a": SECRET}.get,
        nonce_cache=NonceCache(persist_dir=tmp_path, clock=lambda: now[0]),
        clock=lambda: now[0],
    )
    with pytest.raises(PeerError) as err:
        restarted.verify_request(**request)
    assert err.value.reason_code == "executor_internal_error"
    assert "clock rollback" in err.value.detail.lower()


def test_persistent_nonce_recovers_clock_highwater_from_legacy_buckets(tmp_path):
    cache = NonceCache(persist_dir=tmp_path)
    nonce = "b" * 32
    assert cache.check_and_store("node-a", nonce, now=float(NOW + MAX_SKEW_SECONDS))
    marker = tmp_path / "nonce" / "node-a" / "default" / ".clock.highwater"
    marker.unlink()

    with pytest.raises(PeerError) as err:
        cache.check_and_store("node-a", nonce, now=float(NOW - MAX_SKEW_SECONDS))
    assert err.value.reason_code == "executor_internal_error"
    assert "clock rollback" in err.value.detail.lower()


def test_persistent_nonce_corrupt_clock_highwater_fails_closed(tmp_path):
    cache = NonceCache(persist_dir=tmp_path)
    assert cache.check_and_store("node-a", "c" * 32, now=float(NOW))
    marker = tmp_path / "nonce" / "node-a" / "default" / ".clock.highwater"
    marker.write_text("not-a-timestamp", encoding="ascii")

    with pytest.raises(PeerError) as err:
        cache.check_and_store("node-a", "d" * 32, now=float(NOW + 1))
    assert err.value.reason_code == "executor_internal_error"
    assert "high-water corrupted" in err.value.detail.lower()


def test_authenticator_requires_nonce_window_to_cover_both_signature_endpoints(tmp_path):
    short_window = NonceCache(persist_dir=tmp_path, window_seconds=2 * MAX_SKEW_SECONDS - 1)
    with pytest.raises(ValueError, match="nonce window must cover"):
        PeerAuthenticator(
            secret_for={"node-a": SECRET}.get,
            nonce_cache=short_window,
            max_skew_seconds=MAX_SKEW_SECONDS,
        )


def test_memory_nonce_rejects_replay_at_inclusive_expiry_endpoint():
    cache = NonceCache()
    nonce = "e" * 32
    assert cache.check_and_store("node-a", nonce, now=float(NOW))
    assert not cache.check_and_store("node-a", nonce, now=float(NOW + NONCE_WINDOW_SECONDS))
    assert cache.check_and_store("node-a", nonce, now=float(NOW + NONCE_WINDOW_SECONDS + 1))


def test_persistent_nonce_replay_within_same_bucket_is_still_rejected(tmp_path):
    cache = NonceCache(persist_dir=tmp_path, bucket_seconds=NONCE_WINDOW_SECONDS)
    nonce = "f" * 32
    assert cache.check_and_store("node-a", nonce, now=float(NOW + 300))
    # Same-bucket movement does not need a high-water rewrite: the bucket
    # itself remains present and must reject the duplicate.
    assert not cache.check_and_store("node-a", nonce, now=float(NOW + 350))
