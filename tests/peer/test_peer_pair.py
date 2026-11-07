"""配对层：指纹派生、OFFER/CONFIRM 校验、过期与篡改的封闭错误码。"""
from __future__ import annotations

import base64
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from llm_loop.peer.errors import PeerError
from llm_loop.peer.models import utcnow
from llm_loop.peer.pair import (
    CONFIRM_PHRASE,
    Identity,
    build_confirm,
    build_offer,
    decode_link_secret,
    fingerprint_of_b64,
    new_link_secret,
    short_fingerprint,
    verify_confirm,
    verify_ed25519,
    verify_offer,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "lfl.peer.v1"
PUBLIC_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{43}=$")
FP_RE = re.compile(r"^([A-Z2-7]{4}-){7}[A-Z2-7]{4}$")


def _identity() -> Identity:
    return Identity.generate()


def test_identity_roundtrip_and_formats():
    ident = _identity()
    assert PUBLIC_KEY_RE.match(ident.public_key_b64)
    assert FP_RE.match(ident.short_fingerprint)
    copy = Identity.from_private_bytes(ident.private_bytes)
    assert copy.public_key_b64 == ident.public_key_b64
    assert copy.short_fingerprint == ident.short_fingerprint


def test_fingerprint_is_deterministic_and_key_bound():
    a, b = _identity(), _identity()
    assert short_fingerprint(a.public_bytes) == short_fingerprint(a.public_bytes)
    assert a.short_fingerprint != b.short_fingerprint


def test_ed25519_sign_verify():
    ident = _identity()
    sig = ident.sign(b"hello")
    assert verify_ed25519(ident.public_key_b64, b"hello", sig) is True
    assert verify_ed25519(ident.public_key_b64, b"hellp", sig) is False


def test_offer_shape_matches_schema_file():
    jsonschema = pytest.importorskip("jsonschema")
    ident = _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=ident.public_key_b64)
    schema = json.loads((SCHEMA_DIR / "pair-offer.schema.json").read_text())
    jsonschema.validate(offer, schema)


def test_confirm_shape_matches_schema_file():
    jsonschema = pytest.importorskip("jsonschema")
    controller, executor = _identity(), _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=executor.public_key_b64)
    secret_b64, _ = new_link_secret()
    confirm = build_confirm(
        node_id="deepin-01",
        public_key_b64=controller.public_key_b64,
        nonce=offer["nonce"],
        link_secret_b64=secret_b64,
    )
    schema = json.loads((SCHEMA_DIR / "pair-confirm.schema.json").read_text())
    jsonschema.validate(confirm, schema)
    assert confirm["confirm_phrase"] == CONFIRM_PHRASE


def test_offer_happy_path_with_human_verified_fingerprint():
    ident = _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=ident.public_key_b64)
    verified = offer["short_fingerprint"]
    assert verify_offer(offer, expected_fingerprint=verified)["nonce"] == offer["nonce"]


def test_offer_fingerprint_mismatch_one_group_changed():
    ident = _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=ident.public_key_b64)
    tampered = dict(offer, short_fingerprint="K4M2-" + offer["short_fingerprint"][5:])
    with pytest.raises(PeerError) as err:
        verify_offer(tampered)
    assert err.value.reason_code == "pair_fingerprint_mismatch"


def test_offer_rejected_when_human_fingerprint_differs():
    ident = _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=ident.public_key_b64)
    other = _identity()
    with pytest.raises(PeerError) as err:
        verify_offer(offer, expected_fingerprint=other.short_fingerprint)
    assert err.value.reason_code == "pair_fingerprint_mismatch"


def test_offer_with_substituted_public_key_rejected():
    ident, attacker = _identity(), _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=ident.public_key_b64)
    tampered = dict(offer, public_key=attacker.public_key_b64)
    with pytest.raises(PeerError) as err:
        verify_offer(tampered)
    assert err.value.reason_code == "pair_fingerprint_mismatch"


def test_expired_offer_rejected():
    ident = _identity()
    issued = utcnow() - timedelta(seconds=400)
    offer = build_offer(node_id="deepin-01", public_key_b64=ident.public_key_b64, now=issued)
    with pytest.raises(PeerError) as err:
        verify_offer(offer, now=utcnow())
    assert err.value.reason_code == "pair_nonce_expired"


def test_offer_schema_violations_are_bounded():
    ident = _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=ident.public_key_b64)
    for bad in (dict(offer, extra="x"), {k: v for k, v in offer.items() if k != "nonce"},
                dict(offer, key_alg="rsa")):
        with pytest.raises(PeerError) as err:
            verify_offer(bad)
        assert err.value.reason_code == "params_schema_invalid"


@pytest.mark.parametrize("node_id", ["Deepin", "-lead", "a", "x" * 70, "深层-01"])
def test_bad_node_id_rejected(node_id: str):
    with pytest.raises(PeerError) as err:
        build_offer(node_id=node_id, public_key_b64=_identity().public_key_b64)
    assert err.value.reason_code == "params_schema_invalid"


def test_confirm_happy_path_returns_secret_bytes():
    executor = _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=executor.public_key_b64)
    secret_b64, raw = new_link_secret()
    confirm = build_confirm(
        node_id="deepin-01",
        public_key_b64=executor.public_key_b64,
        nonce=offer["nonce"],
        link_secret_b64=secret_b64,
    )
    assert verify_confirm(confirm, offer=offer, now=utcnow()) == raw


def test_confirm_nonce_mismatch_rejected():
    executor = _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=executor.public_key_b64)
    secret_b64, _ = new_link_secret()
    confirm = build_confirm(
        node_id="deepin-01",
        public_key_b64=executor.public_key_b64,
        nonce="f" * 32,
        link_secret_b64=secret_b64,
    )
    with pytest.raises(PeerError) as err:
        verify_confirm(confirm, offer=offer, now=utcnow())
    assert err.value.reason_code == "pair_nonce_expired"


def test_confirm_phrase_and_secret_validation():
    executor = _identity()
    offer = build_offer(node_id="deepin-01", public_key_b64=executor.public_key_b64)
    secret_b64, _ = new_link_secret()
    good = build_confirm(
        node_id="deepin-01",
        public_key_b64=executor.public_key_b64,
        nonce=offer["nonce"],
        link_secret_b64=secret_b64,
    )
    with pytest.raises(PeerError) as err:
        verify_confirm(dict(good, confirm_phrase="YES"), offer=offer, now=utcnow())
    assert err.value.reason_code == "params_schema_invalid"

    short_secret = base64.b64encode(b"too-short").decode("ascii")
    with pytest.raises(PeerError) as err:
        build_confirm(
            node_id="deepin-01",
            public_key_b64=executor.public_key_b64,
            nonce=offer["nonce"],
            link_secret_b64=short_secret,
        )
    assert err.value.reason_code == "params_schema_invalid"


def test_confirm_for_expired_offer_rejected():
    executor = _identity()
    issued = utcnow() - timedelta(seconds=400)
    offer = build_offer(node_id="deepin-01", public_key_b64=executor.public_key_b64, now=issued)
    secret_b64, _ = new_link_secret()
    confirm = build_confirm(
        node_id="deepin-01",
        public_key_b64=executor.public_key_b64,
        nonce=offer["nonce"],
        link_secret_b64=secret_b64,
    )
    with pytest.raises(PeerError) as err:
        verify_confirm(confirm, offer=offer, now=utcnow())
    assert err.value.reason_code == "pair_nonce_expired"


def test_decode_link_secret_rejects_non_base64():
    with pytest.raises(PeerError) as err:
        decode_link_secret("!!!")
    assert err.value.reason_code == "params_schema_invalid"


def test_fingerprint_of_b64_rejects_wrong_length():
    with pytest.raises(PeerError) as err:
        fingerprint_of_b64(base64.b64encode(b"x" * 16).decode("ascii"))
    assert err.value.reason_code == "pair_fingerprint_mismatch"


def test_secret_key_from_store_accepts_base64_and_plaintext():
    from llm_loop.peer.pair import secret_key_from_store

    raw, _ = new_link_secret()
    assert secret_key_from_store(raw) == base64.b64decode(raw)
    assert len(secret_key_from_store("p" * 32)) == 32
    with pytest.raises(PeerError) as err:
        secret_key_from_store("short")
    assert err.value.reason_code == "peer_not_paired"
