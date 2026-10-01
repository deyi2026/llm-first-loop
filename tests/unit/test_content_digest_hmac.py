"""GAP-POL-1 B1: keyed HMAC-SHA256 content digest primitive.

Design: docs/DESIGN-20261002-p0-2-provider-settlement-coverage-plan.md GAP-POL-1.
Canonical JSON reuses the payload-trace `_h` convention
(json.dumps(obj, ensure_ascii=False, sort_keys=True)); the digest itself is
keyed so known-content dictionary attacks on stored digests stop working.
"""

from __future__ import annotations

import json
import os
import re
import stat
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from llm_loop.resources.content_digest import (
    ContentHmacKey,
    ContentHmacKeyError,
    default_key_file,
    resolve_content_hmac_key,
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _hex(n_bytes: int) -> str:
    return os.urandom(n_bytes).hex()


class TestDigestPrimitive:
    def test_digest_is_deterministic_and_full_hex(self) -> None:
        key = ContentHmacKey(key_id="k1", secret=b"a" * 32)
        d1 = key.digest("payload")
        d2 = key.digest("payload")
        assert d1 == d2
        assert _HEX64_RE.match(d1)

    def test_digest_differs_across_data_and_keys(self) -> None:
        k1 = ContentHmacKey(key_id="k1", secret=b"a" * 32)
        k2 = ContentHmacKey(key_id="k2", secret=b"b" * 32)
        assert k1.digest("x") != k1.digest("y")
        assert k1.digest("x") != k2.digest("x")

    def test_digest_matches_independent_hmac_oracle(self) -> None:
        import hashlib
        import hmac as hmac_mod

        secret = b"0123456789abcdef" * 2
        key = ContentHmacKey(key_id="k1", secret=secret)
        expected = hmac_mod.new(secret, b"data", hashlib.sha256).hexdigest()
        assert key.digest(b"data") == expected

    def test_digest_json_reuses_h_canonicalization(self) -> None:
        key = ContentHmacKey(key_id="k1", secret=b"a" * 32)
        obj = {"b": 1, "a": "中文"}
        canon = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
        assert key.digest_json(obj) == key.digest(canon)
        # key order must not matter
        assert key.digest_json({"a": "中文", "b": 1}) == key.digest_json(obj)

    def test_verify_and_verify_json(self) -> None:
        key = ContentHmacKey(key_id="k1", secret=b"a" * 32)
        d = key.digest("data")
        assert key.verify("data", d)
        assert not key.verify("other", d)
        assert not key.verify("data", "0" * 64)
        dj = key.digest_json({"a": 1})
        assert key.verify_json({"a": 1}, dj)
        assert not key.verify_json({"a": 2}, dj)

    def test_secret_minimum_length_enforced(self) -> None:
        with pytest.raises(ContentHmacKeyError):
            ContentHmacKey(key_id="k1", secret=b"short")

    def test_key_rotation_distinguishes_without_losing_old_verification(self) -> None:
        old = ContentHmacKey(key_id="old", secret=b"a" * 32)
        new = ContentHmacKey(key_id="new", secret=b"b" * 32)
        d_old = old.digest_json({"msg": "same content"})
        d_new = new.digest_json({"msg": "same content"})
        assert d_old != d_new
        assert old.verify_json({"msg": "same content"}, d_old)
        assert not new.verify_json({"msg": "same content"}, d_old)
        assert {old.key_id, new.key_id} == {"old", "new"}


class TestExplicitResolution:
    def test_explicit_args_bypass_env_and_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("LFL_CONTENT_HMAC_SECRET", _hex(32))
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        key = resolve_content_hmac_key(secret=b"c" * 32, key_id="explicit")
        assert key.key_id == "explicit"
        assert key.digest("x") == ContentHmacKey(key_id="explicit", secret=b"c" * 32).digest("x")
        assert not default_key_file().exists()


class TestEnvInjection:
    def test_env_secret_hex_with_default_key_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("LFL_CONTENT_HMAC_SECRET", _hex(32))
        key = resolve_content_hmac_key()
        assert key.key_id == "env"
        assert not default_key_file().exists()

    def test_env_secret_custom_key_id(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("LFL_CONTENT_HMAC_SECRET", _hex(32))
        monkeypatch.setenv("LFL_CONTENT_HMAC_KEY_ID", "k9-rotated")
        assert resolve_content_hmac_key().key_id == "k9-rotated"

    def test_env_secret_must_be_hex(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("LFL_CONTENT_HMAC_SECRET", "not-hex!!")
        with pytest.raises(ContentHmacKeyError):
            resolve_content_hmac_key()

    def test_env_secret_must_meet_min_length(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("LFL_CONTENT_HMAC_SECRET", _hex(8))
        with pytest.raises(ContentHmacKeyError):
            resolve_content_hmac_key()


class TestKeyFile:
    def test_autogenerated_once_and_stable_across_resolves(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        k1 = resolve_content_hmac_key()
        k2 = resolve_content_hmac_key()
        assert k1.key_id == k2.key_id
        assert k1.secret_bytes() == k2.secret_bytes()
        path = default_key_file()
        assert path.exists()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["algorithm"] == "hmac-sha256"
        assert raw["key_id"].startswith("k1-")
        assert raw["secret_hex"]
        assert raw["created_at"]

    @pytest.mark.skipif(os.name != "posix", reason="POSIX file mode")
    def test_key_file_mode_0600(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        resolve_content_hmac_key()
        mode = stat.S_IMODE(default_key_file().stat().st_mode)
        assert mode == 0o600

    def test_rotation_by_file_replacement_no_stale_cache(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        old = resolve_content_hmac_key()
        payload = {"m": 1}
        d_old = old.digest_json(payload)
        new_secret = _hex(32)
        default_key_file().write_text(
            json.dumps(
                {
                    "algorithm": "hmac-sha256",
                    "key_id": "k1-rotated",
                    "secret_hex": new_secret,
                    "created_at": "2026-10-02T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        new = resolve_content_hmac_key()
        assert new.key_id == "k1-rotated"
        assert new.digest_json(payload) != d_old
        assert not new.verify_json(payload, d_old)

    def test_key_file_path_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        custom = tmp_path / "custom-key.json"
        monkeypatch.setenv("LFL_CONTENT_HMAC_KEY_FILE", str(custom))
        key = resolve_content_hmac_key()
        assert custom.exists()
        assert json.loads(custom.read_text(encoding="utf-8"))["key_id"] == key.key_id

    @pytest.mark.parametrize(
        "payload",
        [
            "not json",
            json.dumps({"key_id": "x", "secret_hex": "ab" * 32}),  # missing algorithm
            json.dumps({"algorithm": "hmac-sha256", "key_id": "x"}),  # missing secret
            json.dumps({"algorithm": "md5", "key_id": "x", "secret_hex": "ab" * 32}),
            json.dumps({"algorithm": "hmac-sha256", "key_id": "x", "secret_hex": "zz"}),
        ],
    )
    def test_corrupt_key_file_raises_loudly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path, payload: str
    ) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        default_key_file().parent.mkdir(parents=True, exist_ok=True)
        default_key_file().write_text(payload, encoding="utf-8")
        with pytest.raises(ContentHmacKeyError):
            resolve_content_hmac_key()

    def test_allow_create_false_requires_existing_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        with pytest.raises(ContentHmacKeyError):
            resolve_content_hmac_key(allow_create=False)

    def test_concurrent_autogen_resolves_single_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
        barrier = threading.Barrier(8)

        def resolve() -> ContentHmacKey:
            barrier.wait()
            return resolve_content_hmac_key()

        with ThreadPoolExecutor(max_workers=8) as pool:
            keys = list(pool.map(lambda _: resolve(), range(8)))
        assert len({k.key_id for k in keys}) == 1
        assert len({k.secret_bytes() for k in keys}) == 1
