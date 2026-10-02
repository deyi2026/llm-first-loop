"""GAP-POL-1 (P0-2 B1): keyed HMAC-SHA256 content-digest primitive.

Why keyed: digests of user content (payload / rendered text / normalized
responses) are persisted in the settlement journal.  Raw SHA-256 lets anyone
with the journal and a guess of the content confirm the guess (dictionary
attack).  HMAC-SHA256 with a locally-held key removes that oracle while
keeping exact-equality semantics for identical content under one key.

Design contract (docs/DESIGN-20261002-p0-2-provider-settlement-coverage-plan.md
GAP-POL-1):

- canonical JSON reuses the payload-trace ``_h`` convention:
  ``json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")``;
- the digest is full lowercase hex (64 chars);
- ``key_id`` travels with digests so rotation is observable without exposing
  key material;
- key resolution order: explicit args > env injection > local key file
  (auto-generated once, mode 0600, O_EXCL atomic creation);
- this module never logs or exposes the secret; ``secret_bytes()`` exists only
  for owner-side equality checks in tests/operators;
- resolution is a pure function of (args, env, key file): no process-level
  cache, so rotation by file replacement is picked up on the next resolve.
  Consumers on hot paths hold a ``ContentHmacKey`` instance instead;
- failures are loud (``ContentHmacKeyError``); fail-open behaviour belongs to
  the settlement shadow layer, not this primitive.

Env keys (business bootstrap config; registered in the env-access baseline):

- ``LFL_CONTENT_HMAC_SECRET`` — hex-encoded HMAC key (>= 16 bytes), injection
  path for restricted filesystems;
- ``LFL_CONTENT_HMAC_KEY_ID`` — key id for the injected secret (default ``env``);
- ``LFL_CONTENT_HMAC_KEY_FILE`` — key-file path override;
- ``LFL_DATA_DIR`` — data dir root (default ``data``); key file defaults to
  ``<LFL_DATA_DIR>/keys/content_hmac.json``.

Rotation procedure: write a new key file (or change the env pair) and restart
the process.  Digests keep their per-key equality; cross-key comparison is
expected to fail — that is the point of ``key_id``.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_loop.timekeeping import system_local_now_iso

_ALGORITHM = "hmac-sha256"
_MIN_SECRET_BYTES = 16
_GENERATED_KEY_PREFIX = "k1-"

# Serialize first-creation attempts across threads within this process.
_CREATE_LOCK = threading.Lock()


class ContentHmacKeyError(RuntimeError):
    """Raised when a content HMAC key cannot be resolved or is invalid."""


def canonical_json_bytes(obj: Any) -> bytes:
    """Canonical JSON byte form (sorted keys, ensure_ascii=False, utf-8).

    Shared by ``digest_json`` / ``verify_json`` and by call sites that need the
    same bytes for ``projected_bytes`` (GAP-REQ-1). One convention, one place.
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")


# Backwards-compatible private alias for pre-B2 internal references.
_canonical_json_bytes = canonical_json_bytes


@dataclass(frozen=True)
class ContentHmacKey:
    """A resolved HMAC key; produces and verifies keyed content digests."""

    key_id: str
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not self.key_id:
            raise ContentHmacKeyError("key_id must be a non-empty string")
        if len(self.secret) < _MIN_SECRET_BYTES:
            raise ContentHmacKeyError(
                f"HMAC secret must be >= {_MIN_SECRET_BYTES} bytes, got {len(self.secret)}"
            )

    def secret_bytes(self) -> bytes:
        """Owner-side accessor (tests/operators); never logged by this module."""
        return self.secret

    def digest(self, data: bytes | str) -> str:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hmac.new(self.secret, data, hashlib.sha256).hexdigest()

    def digest_json(self, obj: Any) -> str:
        return self.digest(_canonical_json_bytes(obj))

    def verify(self, data: bytes | str, digest_hex: str) -> bool:
        return hmac.compare_digest(self.digest(data), digest_hex)

    def verify_json(self, obj: Any, digest_hex: str) -> bool:
        return hmac.compare_digest(self.digest_json(obj), digest_hex)


def _data_dir() -> Path:
    # literal key on purpose: env gate must see a static name, not <dynamic>
    return Path(os.environ.get("LFL_DATA_DIR", "data"))


def default_key_file() -> Path:
    """Default key-file path: ``<LFL_DATA_DIR|data>/keys/content_hmac.json``."""
    override = os.environ.get("LFL_CONTENT_HMAC_KEY_FILE")
    if override:
        return Path(override)
    return _data_dir() / "keys" / "content_hmac.json"


def _decode_hex_secret(raw: str, *, source: str) -> bytes:
    raw = raw.strip()
    try:
        material = bytes.fromhex(raw)
    except ValueError as exc:
        raise ContentHmacKeyError(
            f"{source} must be hex-encoded (got {len(raw)} non-hex chars)"
        ) from exc
    if len(material) < _MIN_SECRET_BYTES:
        raise ContentHmacKeyError(
            f"{source} decodes to {len(material)} bytes; minimum is {_MIN_SECRET_BYTES}"
        )
    return material


def _parse_key_file(path: Path) -> ContentHmacKey:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentHmacKeyError(f"content HMAC key file {path} is unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContentHmacKeyError(f"content HMAC key file {path} must contain a JSON object")
    algorithm = raw.get("algorithm")
    key_id = raw.get("key_id")
    secret_hex = raw.get("secret_hex")
    if algorithm != _ALGORITHM:
        raise ContentHmacKeyError(f"key file {path}: unsupported algorithm {algorithm!r}")
    if not isinstance(key_id, str) or not key_id:
        raise ContentHmacKeyError(f"key file {path}: key_id must be a non-empty string")
    if not isinstance(secret_hex, str):
        raise ContentHmacKeyError(f"key file {path}: secret_hex must be a hex string")
    return ContentHmacKey(
        key_id=key_id,
        secret=_decode_hex_secret(secret_hex, source=f"key file {path} secret_hex"),
    )


def _create_key_file(path: Path) -> ContentHmacKey:
    """Create a fresh key file atomically (0600); race losers parse the winner's.

    The payload is written to a unique temp file and moved into place with
    ``os.replace`` so ``path.exists()`` implies complete, parseable content
    (no partial-file window for concurrent readers).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with _CREATE_LOCK:
        if path.exists():
            return _parse_key_file(path)
        key = ContentHmacKey(
            key_id=f"{_GENERATED_KEY_PREFIX}{secrets.token_hex(4)}",
            secret=secrets.token_bytes(32),
        )
        payload = json.dumps(
            {
                "algorithm": _ALGORITHM,
                "key_id": key.key_id,
                # hex of the raw key bytes; the file itself is the secret carrier
                "secret_hex": key.secret_bytes().hex(),
                "created_at": system_local_now_iso(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                with contextlib.suppress(OSError):
                    tmp.unlink()
        return key


def resolve_content_hmac_key(
    *,
    secret: bytes | str | None = None,
    key_id: str | None = None,
    key_file: str | Path | None = None,
    allow_create: bool = True,
) -> ContentHmacKey:
    """Resolve the content HMAC key.

    Order: explicit ``secret`` > env ``LFL_CONTENT_HMAC_SECRET`` > key file
    (auto-generated on first use unless ``allow_create=False``).
    """
    if secret is not None:
        material = secret.encode("utf-8") if isinstance(secret, str) else secret
        resolved_id = key_id or os.environ.get("LFL_CONTENT_HMAC_KEY_ID") or "explicit"
        return ContentHmacKey(key_id=resolved_id, secret=material)

    injected_secret = os.environ.get("LFL_CONTENT_HMAC_SECRET")
    if injected_secret:
        material = _decode_hex_secret(injected_secret, source="env LFL_CONTENT_HMAC_SECRET")
        resolved_id = key_id or os.environ.get("LFL_CONTENT_HMAC_KEY_ID") or "env"
        return ContentHmacKey(key_id=resolved_id, secret=material)

    path = Path(key_file) if key_file is not None else default_key_file()
    if path.exists():
        return _parse_key_file(path)
    if not allow_create:
        raise ContentHmacKeyError(
            f"content HMAC key file {path} does not exist and allow_create=False"
        )
    return _create_key_file(path)


def normalized_response_hmac(
    content: str | None,
    reasoning_content: str | None,
    tool_calls: list[dict[str, object]] | None,
    *,
    allow_create: bool = True,
) -> tuple[str | None, str | None]:
    """GAP-RESP-1 (C1): keyed hmac over the normalized assistant-message projection.

    ``tool_calls`` rows must already be normalized to ``{id, name, arguments}``
    (arguments kept as-is: parsed object or string; canonical JSON makes both
    deterministic).  Returns ``(digest_hex, key_id)``.  Key-resolution failures
    propagate (``ContentHmacKeyError``, loud primitive per module contract) —
    the settlement shadow layer catches and omits honestly; this wrapper exists
    so API and web transports build the identical projection
    ``{"content": ..., "reasoning_content": ..., "tool_calls": ...}``.

    Shadow call sites pass ``allow_create=False``: an observation layer must
    never provision key material as a side effect of a provider call.
    """
    projection = {
        "content": content,
        "reasoning_content": reasoning_content,
        "tool_calls": tool_calls or [],
    }
    key = resolve_content_hmac_key(allow_create=allow_create)
    return key.digest(canonical_json_bytes(projection)), key.key_id
