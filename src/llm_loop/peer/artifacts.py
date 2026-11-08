"""产物仓库：内容寻址 + 落盘即校验（数据面不内联，DESIGN §5.5）。

ref 形态：``artifact://v1/<sha256>``（过 receipt.schema.json 的
``^artifact://v1/[A-Za-z0-9._-]{8,128}$``；64 位 hex 落在字符集内）。
内容寻址意味着 ref 由内容决定：读回时重算 sha256 与 ref 比对，
不符即 ``artifact_digest_mismatch``（fail-closed，不返回可疑字节）。
落盘 0600（产物可能含截图/日志等敏感内容）。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .errors import PeerError

REF_PREFIX = "artifact://v1/"
_REF_RE = re.compile(r"^artifact://v1/([A-Za-z0-9._-]{8,128})$")
_SHA_RE = re.compile(r"^[a-f0-9]{64}$")
DEFAULT_MAX_BYTES = 8 * 1024 * 1024


class ArtifactStore:
    def __init__(self, root: Path | str, *, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self._root = Path(root)
        self._max_bytes = int(max_bytes)

    @property
    def root(self) -> Path:
        return self._root

    def put(self, data: bytes, *, media_type: str | None = None) -> dict[str, Any]:
        if len(data) > self._max_bytes:
            raise PeerError("params_schema_invalid", f"artifact too large: {len(data)} bytes")
        digest = hashlib.sha256(data).hexdigest()
        target = self._path_for(digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.chmod(tmp, 0o600)
                os.replace(tmp, target)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        descriptor: dict[str, Any] = {
            "ref": REF_PREFIX + digest,
            "sha256": digest,
            "bytes": len(data),
        }
        if media_type:
            descriptor["media_type"] = media_type[:100]
        return descriptor

    def read(self, ref: str) -> bytes:
        digest = self._digest_of(ref)
        target = self._path_for(digest)
        try:
            data = target.read_bytes()
        except FileNotFoundError:
            raise PeerError("artifact_missing", ref) from None
        if hashlib.sha256(data).hexdigest() != digest:
            raise PeerError("artifact_digest_mismatch", ref)
        return data

    def exists(self, ref: str) -> bool:
        return self._path_for(self._digest_of(ref)).exists()

    def _digest_of(self, ref: str) -> str:
        match = _REF_RE.match(ref or "")
        if not match:
            raise PeerError("params_schema_invalid", f"malformed artifact ref: {ref!r}")
        digest = match.group(1)
        if not _SHA_RE.match(digest):
            raise PeerError("params_schema_invalid", "artifact ref must be content-addressed sha256")
        return digest

    def _path_for(self, digest: str) -> Path:
        return self._root / "objects" / digest[:2] / digest
