"""Peer 配对：Ed25519 身份 + 短指纹 + PAIR-OFFER/CONFIRM（lfl.peer.v1）。

形状真值源：``docs/schemas/lfl.peer.v1/pair-offer.schema.json`` /
``pair-confirm.schema.json``（本模块的 build_* 输出必须能直接过 schema 校验）。

短指纹派生（两侧必须一致，改动=契约变更）：
    base64.b32encode(sha256(public_key_raw).digest()[:20]) → 32 字符（字符集 A-Z2-7）
    → 每 4 字符一组，"-" 连接 → 如 K4M2-P7QX-...-3LQE
    20 字节 正好编码成 32 字符无填充，因此不需要处理 '=' 对齐。

安全口径（不夸大）：
- 短指纹防的是"SSH 主机密钥已被替换但仍想蒙混过关"，它是人眼比对用的，不是加密边界。
- ``confirm_phrase`` 是摩擦设计，不是安全边界（脚本同样能写出该常量）。
- ``link_secret`` 由控制端生成（32 随机字节 base64），经 SSH 隧道随 PAIR-CONFIRM 传入；
  受控端以 0600 落盘（``PeerStore.write_secret``）。它只允许出现在配对消息里，
  不得进入常规审计与请求日志——审计只记 node_id + short_fingerprint。
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .errors import PeerError
from .models import iso, parse_ts, utcnow

SCHEMA_VERSION = "lfl.peer.v1"
KEY_ALG = "ed25519"
CONFIRM_PHRASE = "I-HAVE-VERIFIED-THE-SHORT-FINGERPRINT"
PAIR_TTL_SECONDS = 300

_NODE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_NONCE_RE = re.compile(r"^[a-f0-9]{32}$")
_FP_RE = re.compile(r"^([A-Z2-7]{4}-){7}[A-Z2-7]{4}$")
_OFFER_FIELDS = frozenset(
    {"schema", "node_id", "key_alg", "public_key", "short_fingerprint", "nonce", "issued_at", "expires_at"}
)
_CONFIRM_FIELDS = frozenset(
    {"schema", "node_id", "key_alg", "public_key", "short_fingerprint", "nonce", "confirm_phrase", "link_secret"}
)


class Identity:
    """节点身份：私钥种子（32 字节）只在本机内存/0600 文件里，公钥可外发。"""

    __slots__ = ("_private",)

    def __init__(self, private: Ed25519PrivateKey) -> None:
        self._private = private

    @classmethod
    def generate(cls) -> Identity:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_private_bytes(cls, raw: bytes) -> Identity:
        if len(raw) != 32:
            raise ValueError("ed25519 seed must be 32 bytes")
        return cls(Ed25519PrivateKey.from_private_bytes(raw))

    @property
    def private_bytes(self) -> bytes:
        from cryptography.hazmat.primitives import serialization

        return self._private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    @property
    def public_bytes(self) -> bytes:
        from cryptography.hazmat.primitives import serialization

        return self._private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_bytes).decode("ascii")

    @property
    def short_fingerprint(self) -> str:
        return short_fingerprint(self.public_bytes)

    def sign(self, message: bytes) -> str:
        return base64.b64encode(self._private.sign(message)).decode("ascii")


def short_fingerprint(public_key_raw: bytes) -> str:
    """sha256(公钥原始 32 字节) 前 20 字节 → base32 → 8 组 × 4。"""
    if len(public_key_raw) != 32:
        raise ValueError("ed25519 public key must be 32 bytes")
    digest = hashlib.sha256(public_key_raw).digest()[:20]
    encoded = base64.b32encode(digest).decode("ascii")
    return "-".join(encoded[i : i + 4] for i in range(0, 32, 4))


def fingerprint_of_b64(public_key_b64: str) -> str:
    return short_fingerprint(_decode_public_key(public_key_b64))


def _decode_public_key(public_key_b64: str) -> bytes:
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except Exception:
        raise PeerError("pair_fingerprint_mismatch", "public_key not base64") from None
    if len(raw) != 32:
        raise PeerError("pair_fingerprint_mismatch", "public_key not 32 bytes")
    return raw


def verify_ed25519(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    """身份签名校验（配对期/审计用途）；返回布尔，不抛。"""
    try:
        key = Ed25519PublicKey.from_public_bytes(_decode_public_key(public_key_b64))
        key.verify(base64.b64decode(signature_b64, validate=True), message)
    except (PeerError, InvalidSignature, ValueError):
        return False
    return True


def new_nonce() -> str:
    return secrets.token_hex(16)


def new_link_secret() -> tuple[str, bytes]:
    """控制端生成 link_secret：返回 (base64, raw)。"""
    raw = secrets.token_bytes(32)
    return base64.b64encode(raw).decode("ascii"), raw


def decode_link_secret(link_secret_b64: str) -> bytes:
    try:
        raw = base64.b64decode(link_secret_b64, validate=True)
    except Exception:
        raise PeerError("params_schema_invalid", "link_secret not base64") from None
    if len(raw) != 32:
        raise PeerError("params_schema_invalid", "link_secret not 32 bytes")
    return raw


def _require_node_id(node_id: str) -> None:
    if not _NODE_ID_RE.match(node_id or ""):
        raise PeerError("params_schema_invalid", f"bad node_id: {node_id!r}")


def _require_exact_fields(payload: Mapping[str, Any], expected: frozenset[str], what: str) -> None:
    got = set(payload)
    if got != set(expected):
        missing = sorted(set(expected) - got)
        extra = sorted(got - set(expected))
        raise PeerError("params_schema_invalid", f"{what} fields missing={missing} extra={extra}")


def build_offer(
    *,
    node_id: str,
    public_key_b64: str,
    nonce: str | None = None,
    ttl_seconds: int = PAIR_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    _require_node_id(node_id)
    issued = now or utcnow()
    return {
        "schema": SCHEMA_VERSION,
        "node_id": node_id,
        "key_alg": KEY_ALG,
        "public_key": public_key_b64,
        "short_fingerprint": fingerprint_of_b64(public_key_b64),
        "nonce": nonce or new_nonce(),
        "issued_at": iso(issued),
        "expires_at": iso(issued + timedelta(seconds=int(ttl_seconds))),
    }


def verify_offer(
    offer: Mapping[str, Any],
    *,
    expected_fingerprint: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """校验 OFFER：形状 → 指纹自洽 → 指纹匹配（人眼核对值）→ 未过期。

    返回原 payload（不改写）。抛 PeerError 的 reason_code ∈
    {params_schema_invalid, pair_fingerprint_mismatch, pair_nonce_expired}。
    """
    _require_exact_fields(offer, _OFFER_FIELDS, "pair_offer")
    _require_node_id(str(offer["node_id"]))
    if offer["schema"] != SCHEMA_VERSION or offer["key_alg"] != KEY_ALG:
        raise PeerError("params_schema_invalid", "schema/key_alg mismatch")
    declared = str(offer["short_fingerprint"])
    if not _FP_RE.match(declared):
        raise PeerError("pair_fingerprint_mismatch", "malformed short_fingerprint")
    computed = fingerprint_of_b64(str(offer["public_key"]))
    if computed != declared:
        raise PeerError("pair_fingerprint_mismatch", f"declared={declared} computed={computed}")
    if expected_fingerprint is not None and computed != expected_fingerprint.strip().upper():
        raise PeerError("pair_fingerprint_mismatch", "does not match human-verified fingerprint")
    if not _NONCE_RE.match(str(offer["nonce"])):
        raise PeerError("params_schema_invalid", "malformed nonce")
    moment = now or utcnow()
    try:
        expires = parse_ts(str(offer["expires_at"]))
    except ValueError:
        raise PeerError("params_schema_invalid", "malformed expires_at") from None
    if moment >= expires:
        raise PeerError("pair_nonce_expired", f"expired at {iso(expires)}")
    return dict(offer)


def build_confirm(
    *,
    node_id: str,
    public_key_b64: str,
    nonce: str,
    link_secret_b64: str,
) -> dict[str, Any]:
    """控制端生成 CONFIRM；link_secret 必须是 new_link_secret() 的 base64 分支。"""
    _require_node_id(node_id)
    decode_link_secret(link_secret_b64)
    if not _NONCE_RE.match(nonce or ""):
        raise PeerError("params_schema_invalid", "malformed nonce")
    return {
        "schema": SCHEMA_VERSION,
        "node_id": node_id,
        "key_alg": KEY_ALG,
        "public_key": public_key_b64,
        "short_fingerprint": fingerprint_of_b64(public_key_b64),
        "nonce": nonce,
        "confirm_phrase": CONFIRM_PHRASE,
        "link_secret": link_secret_b64,
    }


def verify_confirm(
    confirm: Mapping[str, Any],
    *,
    offer: Mapping[str, Any],
    now: datetime | None = None,
) -> bytes:
    """受控端校验 CONFIRM 并返回 link_secret 原始字节（落盘由调用方做，0600）。"""
    _require_exact_fields(confirm, _CONFIRM_FIELDS, "pair_confirm")
    verify_offer(offer, expected_fingerprint=str(offer.get("short_fingerprint")), now=now)
    if confirm["schema"] != SCHEMA_VERSION or confirm["key_alg"] != KEY_ALG:
        raise PeerError("params_schema_invalid", "schema/key_alg mismatch")
    if str(confirm["confirm_phrase"]) != CONFIRM_PHRASE:
        raise PeerError("params_schema_invalid", "confirm_phrase mismatch")
    if str(confirm["nonce"]) != str(offer["nonce"]):
        raise PeerError("pair_nonce_expired", "nonce does not match offer")
    if str(confirm["node_id"]) != str(offer["node_id"]):
        raise PeerError("pair_fingerprint_mismatch", "node_id mismatch")
    if str(confirm["public_key"]) != str(offer["public_key"]):
        raise PeerError("pair_fingerprint_mismatch", "public_key mismatch")
    if str(confirm["short_fingerprint"]) != str(offer["short_fingerprint"]):
        raise PeerError("pair_fingerprint_mismatch", "short_fingerprint mismatch")
    return decode_link_secret(str(confirm["link_secret"]))
