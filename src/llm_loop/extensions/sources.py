"""P2-B 安装源获取：Git URL 与归档（设计 §5.2 / FR-12）.

纪律（与 §5.2 一一对应）：
- 源固定：git 源把分支/tag 解析到具体 commit（locator ``git+URL@commit``）；
  归档源固定到内容 digest（locator ``archive:URL#sha256=HEX``）。
- 无副作用：不递归 submodule、不执行任何安装脚本/构建命令（只读文件，
  从不执行包内代码）；git 调用禁终端提示与凭证助手交互，禁用本地钩子。
- 解压安全：路径必须落在目标目录内（拒绝绝对路径与 ``..``）、拒绝
  symlink/硬链接/设备/FIFO 等特殊条目、拒绝重复条目冲突；受
  条目数/单文件/总解压字节数上限约束。
- 完整性 ≠ 真实性：digest 只证明内容完整性（未篡改）；来源真实性
  （托管信誉、签名、授权）不由本机制声称，须由安装者另行核验。
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

__all__ = [
    "MAX_ARCHIVE_BYTES",
    "MAX_ARCHIVE_ENTRIES",
    "MAX_EXTRACTED_BYTES",
    "FetchedSource",
    "SourceRejectedError",
    "fetch_git_source",
    "fetch_archive_source",
    "install_fetched",
]

#: 归档字节上限（下载/读取侧）
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
#: 解压条目数上限
MAX_ARCHIVE_ENTRIES = 4096
#: 解压总字节上限
MAX_EXTRACTED_BYTES = 256 * 1024 * 1024

_ALLOWED_GIT_SCHEMES = ("https://", "http://", "ssh://", "git://", "file://")


class SourceRejectedError(Exception):
    """源获取被拒绝（路径越界/特殊条目/上限/digest 不符等），如实携带原因."""


@dataclass(frozen=True)
class FetchedSource:
    """获取结果：本地包根 + 固定源标识 + 完整性摘要 + 诚实元数据."""

    root: Path
    locator: str
    integrity: str  # sha256:...（归档字节摘要 / git 场景为 commit 已在 locator）
    fetch_meta: dict = field(default_factory=dict)

    def note(self) -> str:
        """人读摘要（完整性与真实性分开表述，§5.2）."""
        parts = [f"locator={self.locator}", f"integrity={self.integrity}"]
        if self.fetch_meta:
            parts.append(f"meta={self.fetch_meta}")
        return " ".join(parts)


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ── Git 源 ────────────────────────────────────────────────────────────


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/true",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": "",
            "GIT_CONFIG_KEY_1": "protocol.file.allow",
            "GIT_CONFIG_VALUE_1": "always",
        }
    )
    return env


def fetch_git_source(
    url: str,
    *,
    ref: str = "HEAD",
    dest: str | Path | None = None,
    timeout_s: float = 120.0,
) -> FetchedSource:
    """git 源获取：ref（分支/tag/commit）解析并固定到具体 commit.

    - 不递归 submodule（§5.2）；不执行包内任何脚本/构建（LFL 只读文件）。
    - ``protocol.file.allow=always`` 仅为允许本地 file:// 源（测试/内网镜像）；
      交互提示与凭证助手全部禁用。
    """
    url = str(url or "").strip()
    ref = str(ref or "HEAD").strip() or "HEAD"
    if not url or url.startswith("-") or "\n" in url or "\r" in url:
        raise SourceRejectedError(f"git url 非法: {url!r:.120}")
    if ref.startswith("-") or "\n" in ref or "\r" in ref or not ref:
        raise SourceRejectedError(f"git ref 非法: {ref!r:.60}")
    if not (url.startswith(_ALLOWED_GIT_SCHEMES) or Path(url).exists()):
        raise SourceRejectedError(
            f"git url scheme 不支持: {url!r:.120}（允许 {','.join(_ALLOWED_GIT_SCHEMES)} 或本地路径）"
        )
    root = Path(dest) if dest else Path(tempfile.mkdtemp(prefix="lfl-git-src-"))
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise SourceRejectedError(f"目标目录非空: {root}")
    root.mkdir(parents=True, exist_ok=True)

    def _git(*args: str) -> str:
        proc = subprocess.run(  # noqa: S603 — 参数固定、无 shell
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=_git_env(),
        )
        if proc.returncode != 0:
            raise SourceRejectedError(
                f"git {' '.join(args[:2])} 失败（{url!r:.120}@{ref}）: {proc.stderr.strip()[:300]}"
            )
        return proc.stdout.strip()

    try:
        _git("init", "--quiet")
        _git("remote", "add", "origin", url)
        _git("-c", "fetch.pruneTags=false", "fetch", "--depth", "1", "--no-tags", "origin", ref)
        _git("checkout", "--quiet", "FETCH_HEAD")
        commit = _git("rev-parse", "HEAD")
    except SourceRejectedError:
        shutil.rmtree(root, ignore_errors=True)
        raise
    if len(commit) < 40:
        shutil.rmtree(root, ignore_errors=True)
        raise SourceRejectedError(f"git commit 解析异常: {commit!r:.80}")
    locator = f"git+{url}@{commit}"
    meta = {"requested_ref": ref, "resolved_commit": commit, "submodules": "disabled", "side_effects": "none"}
    return FetchedSource(
        root=root,
        locator=locator,
        integrity=f"sha256:{hashlib.sha256(locator.encode()).hexdigest()}",
        fetch_meta=meta,
    )


# ── 归档源 ────────────────────────────────────────────────────────────


def _check_member_path(raw_name: str) -> PurePosixPath:
    """条目路径校验：拒绝绝对路径、..、空段（防 zip-slip/越界）."""
    if not raw_name or "\x00" in raw_name:
        raise SourceRejectedError(f"归档条目名非法: {raw_name!r:.120}")
    p = PurePosixPath(raw_name)
    if p.is_absolute() or raw_name.startswith("/") or (len(raw_name) > 1 and raw_name[1] == ":"):
        raise SourceRejectedError(f"归档条目为绝对路径: {raw_name!r:.120}")
    parts = p.parts
    if any(part == ".." for part in parts):
        raise SourceRejectedError(f"归档条目含 '..'（越界拒绝）: {raw_name!r:.120}")
    if any(part in ("", ".") for part in parts):
        raise SourceRejectedError(f"归档条目路径段异常: {raw_name!r:.120}")
    return p


def _download_or_locate(url_or_path: str, *, timeout_s: float) -> Path:
    """http(s) 下载到临时文件（流式限额）或校验本地路径."""
    spec = str(url_or_path or "").strip()
    if not spec:
        raise SourceRejectedError("归档源为空")
    if spec.startswith("http://") or spec.startswith("https://"):
        import urllib.request

        fd, tmp_name = tempfile.mkstemp(prefix="lfl-arc-")
        os.close(fd)
        try:
            with (
                urllib.request.urlopen(spec, timeout=timeout_s) as resp,  # noqa: S310
                open(tmp_name, "wb") as sink,
            ):
                total = 0
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise SourceRejectedError(
                            f"归档超过大小上限 {MAX_ARCHIVE_BYTES} 字节（下载中止）"
                        )
                    sink.write(chunk)
            return Path(tmp_name)
        except Exception:
            os.unlink(tmp_name)
            raise
    if spec.startswith("-"):
        raise SourceRejectedError(f"归档源路径非法: {spec!r:.60}")
    path = Path(spec).expanduser()
    if not path.is_file():
        raise SourceRejectedError(f"归档文件不存在或非普通文件: {spec!r:.120}")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise SourceRejectedError(
            f"归档超过大小上限 {MAX_ARCHIVE_BYTES} 字节: {spec}（{path.stat().st_size}）"
        )
    return path


def _extract_zip(path: Path, out: Path) -> None:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise SourceRejectedError(f"zip 损坏: {exc}") from exc
    seen: set[str] = set()
    entries = 0
    total = 0
    with zf:
        for info in zf.infolist():
            entries += 1
            if entries > MAX_ARCHIVE_ENTRIES:
                raise SourceRejectedError(f"归档条目超过 {MAX_ARCHIVE_ENTRIES} 上限")
            rel = _check_member_path(info.filename)
            target = out.joinpath(*rel.parts)
            mode = info.external_attr >> 16
            is_symlink = (mode & 0o170000) == 0o120000
            if info.create_system == 3 and is_symlink:
                raise SourceRejectedError(f"symlink 条目拒绝: {info.filename!r:.120}（§5.2 特殊条目）")
            key = str(rel)
            if key in seen:
                raise SourceRejectedError(f"重复条目冲突拒绝: {info.filename!r:.120}")
            seen.add(key)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if info.file_size > MAX_EXTRACTED_BYTES:
                raise SourceRejectedError(f"单条目解压超过上限: {info.filename!r:.60}")
            with zf.open(info) as src, open(target, "wb") as dst:
                written = 0
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    total += len(chunk)
                    if written > info.file_size + 1024 * 1024 or total > MAX_EXTRACTED_BYTES:
                        raise SourceRejectedError("解压总量超上限（疑似 zip 炸弹）")
                    dst.write(chunk)
            os.chmod(target, 0o644)


def _extract_tar(path: Path, out: Path) -> None:
    entries = 0
    total = 0
    seen: set[str] = set()
    try:
        with tarfile.open(path, mode="r:*") as tf:
            return _drain_tar(tf, out, seen, entries, total)
    except tarfile.TarError as exc:
        raise SourceRejectedError(f"tar 损坏: {exc}") from exc


def _drain_tar(tf: tarfile.TarFile, out: Path, seen: set[str], entries: int, total: int) -> None:
    for member in tf:
            entries += 1
            if entries > MAX_ARCHIVE_ENTRIES:
                raise SourceRejectedError(f"归档条目超过 {MAX_ARCHIVE_ENTRIES} 上限")
            rel = _check_member_path(member.name)
            if member.issym() or member.islnk():
                raise SourceRejectedError(f"symlink/硬链接条目拒绝: {member.name!r:.120}（§5.2 特殊条目）")
            if member.isdev() or member.isfifo():
                raise SourceRejectedError(f"设备/FIFO 条目拒绝: {member.name!r:.120}（§5.2 特殊条目）")
            key = str(rel)
            if key in seen:
                raise SourceRejectedError(f"重复条目冲突拒绝: {member.name!r:.120}")
            seen.add(key)
            target = out.joinpath(*rel.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise SourceRejectedError(f"未知类型条目拒绝: {member.name!r:.120}（type={member.type}）")
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.size > MAX_EXTRACTED_BYTES:
                raise SourceRejectedError(f"单条目解压超过上限: {member.name!r:.60}")
            src = tf.extractfile(member)
            if src is None:
                raise SourceRejectedError(f"条目内容不可读: {member.name!r:.120}")
            with src, open(target, "wb") as dst:
                written = 0
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    total += len(chunk)
                    if written > member.size + 1024 * 1024 or total > MAX_EXTRACTED_BYTES:
                        raise SourceRejectedError("解压总量超上限（疑似 tar 炸弹）")
                    dst.write(chunk)
            os.chmod(target, 0o644)


def _unwrap_single_top_dir(out: Path) -> tuple[Path, str | None]:
    """tarball 常见单顶层目录布局 → 解包为包根（记录在元数据）."""
    children = [c for c in out.iterdir() if c.name not in (".", "..")]
    if len(children) == 1 and children[0].is_dir():
        return children[0], children[0].name
    return out, None


def fetch_archive_source(
    url_or_path: str,
    *,
    expected_sha256: str | None = None,
    dest: str | Path | None = None,
    timeout_s: float = 60.0,
) -> FetchedSource:
    """归档源获取：zip/tar(.gz/.bz2/.xz) 安全校验解压；固定到内容 digest.

    ``expected_sha256`` 提供时强校验（PinnedIntegrity：不匹配即拒绝）。
    未提供时按实际内容记录 digest（安装者仍可事后核验，机制不声称真实性）。
    """
    archive = _download_or_locate(url_or_path, timeout_s=timeout_s)
    owned_temp = archive.parent.name.startswith("tmp") and archive.name.startswith("lfl-arc-")
    try:
        digest = _sha256_of_file(archive)
        if expected_sha256:
            want = expected_sha256.strip().lower().removeprefix("sha256:")
            if want != digest:
                raise SourceRejectedError(
                    f"归档 digest 不匹配（预期 sha256:{want}，实际 sha256:{digest}）"
                )
        out = Path(dest).resolve() if dest else Path(tempfile.mkdtemp(prefix="lfl-arc-src-"))
        out.mkdir(parents=True, exist_ok=True)
        if any(out.iterdir()):
            raise SourceRejectedError(f"目标目录非空: {out}")
        with open(archive, "rb") as fh:
            head = fh.read(4)
        if head[:4] == b"PK\x03\x04":
            _extract_zip(archive, out)
            kind = "zip"
        else:
            _extract_tar(archive, out)
            kind = "tar"
        root, unwrapped = _unwrap_single_top_dir(out)
        entries = sum(1 for _ in root.rglob("*"))
        locator = f"archive:{url_or_path}#sha256={digest}"
        meta = {
            "format": kind,
            "entries": entries,
            "unwrapped_top_dir": unwrapped or "",
            "authenticity": "not-claimed（digest 仅证明完整性；真实性须安装者另行核验）",
        }
        return FetchedSource(root=root, locator=locator, integrity=f"sha256:{digest}", fetch_meta=meta)
    finally:
        if owned_temp:
            with contextlib.suppress(OSError):
                os.unlink(archive)


def install_fetched(
    store: object,
    fetched: FetchedSource,
    *,
    scopes: list[str] | None = None,
    expected_revision: int = 0,
) -> object:
    """获取结果 → store.install（源固定 locator 记入 InstallRecord.source）.

    store.install 复制包内容（digest 寻址），临时目录随后清理。
    """
    try:
        return store.install(
            fetched.root,
            source=fetched.locator,
            scopes=scopes,
            expected_revision=expected_revision,
        )
    finally:
        shutil.rmtree(fetched.root, ignore_errors=True)
