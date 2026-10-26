"""Contract tests for the user-scoped Linux installer and uninstaller.

These tests exercise the shell transaction against isolated HOME directories. On macOS,
the OS-identification and GNU utility commands are stubbed; this is not a substitute for
the native Linux acceptance job.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path

import pytest

from tests import env_channel

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install_linux.sh"
UNINSTALLER = ROOT / "scripts" / "uninstall_linux.sh"


def _wheel(path: Path, version: str) -> str:
    dist_info = f"llm_first_loop-{version}.dist-info"
    metadata = (
        "Metadata-Version: 2.1\n"
        "Name: llm-first-loop\n"
        f"Version: {version}\n"
        "\n"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def linux_shell(tmp_path: Path) -> dict[str, str]:
    """Create a Linux-shaped command environment without touching the user's HOME."""
    home = tmp_path / "home"
    home.mkdir()
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_path = os.environ.get("PATH", "/usr/bin:/bin")

    (bin_dir / "uname").write_text(
        "#!/bin/sh\n"
        "case \"${1:-}\" in\n"
        "  -s) printf '%s\\n' \"${FAKE_UNAME_S:-Linux}\" ;;\n"
        "  -m) printf '%s\\n' \"${FAKE_UNAME_M:-x86_64}\" ;;\n"
        "  *) printf '%s\\n' unknown ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (bin_dir / "curl").write_text(
        "#!/bin/sh\n"
        "out=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -o) shift; out=\"$1\" ;;\n"
        "  esac\n"
        "  shift\n"
        "done\n"
        "[ -z \"$out\" ] || printf '%s\\n' '{\"message\":\"Not Found\"}' > \"$out\"\n"
        "printf '404'\n",
        encoding="utf-8",
    )
    real_stat = shutil.which("stat")
    assert real_stat, "a stat command is required to test the installer"
    (bin_dir / "stat").write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = '-c' ] && [ \"${2:-}\" = '%u' ]; then id -u; exit $?; fi\n"
        f"exec {real_stat} \"$@\"\n",
        encoding="utf-8",
    )
    (bin_dir / "getconf").write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = 'GNU_LIBC_VERSION' ]; then printf '%s\\n' \"${FAKE_GLIBC_VERSION:-glibc 2.35}\"; exit 0; fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (bin_dir / "ps").write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"${FAKE_PS_LINES:-}\"\n",
        encoding="utf-8",
    )
    real_hash = shutil.which("sha256sum") or shutil.which("shasum")
    assert real_hash, "a SHA-256 command is required to test the installer"
    hash_name = Path(real_hash).name
    hash_args = "-a 256 \"$@\"" if hash_name == "shasum" else "\"$@\""
    check_args = "-a 256 -c \"$3\"" if hash_name == "shasum" else "-c \"$3\""
    (bin_dir / "sha256sum").write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = '--check' ]; then\n"
        f"  {real_hash} {check_args} >/dev/null 2>&1\n"
        "  exit $?\n"
        "fi\n"
        f"exec {real_hash} {hash_args}\n",
        encoding="utf-8",
    )
    (bin_dir / "uv").write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            set -eu
            if [ "${1:-}" = "venv" ]; then
              shift
              target=''
              for arg in "$@"; do target="$arg"; done
              mkdir -p "$target/bin"
              ln -s "$(command -v python3)" "$target/bin/python"
              exit 0
            fi
            if [ "${1:-}" = "pip" ] && [ "${2:-}" = "install" ]; then
              shift 2
              python_bin=''
              wheel=''
              while [ $# -gt 0 ]; do
                if [ "$1" = "--python" ]; then
                  shift
                  python_bin="$1"
                else
                  wheel="$1"
                fi
                shift
              done
              version="$("$python_bin" - "$wheel" <<'PY'
            import email, sys, zipfile
            with zipfile.ZipFile(sys.argv[1]) as z:
                name = next(n for n in z.namelist() if n.endswith('/METADATA'))
                print(email.message_from_bytes(z.read(name))['Version'])
            PY
            )"
              if [ "${FAKE_UV_FAIL_VERSION:-}" = "$version" ]; then exit 73; fi
              cat > "$(dirname "$python_bin")/lfl" <<EOF
            #!/bin/sh
            case "\\${1:-}" in
              --version) printf 'llm-first-loop %s\\n' '$version' ;;
              check-install) printf '{"ok":true}\\n' ;;
              *) exit 0 ;;
            esac
            EOF
              chmod 755 "$(dirname "$python_bin")/lfl"
              exit 0
            fi
            if [ "${1:-}" = "pip" ] && [ "${2:-}" = "check" ]; then exit 0; fi
            echo "unexpected fake uv arguments: $*" >&2
            exit 2
            """
        ),
        encoding="utf-8",
    )
    for command in bin_dir.iterdir():
        command.chmod(0o755)
    return {
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "PATH": f"{bin_dir}:{real_path}",
        "LFL_HOME": str(home / ".local" / "share" / "lfl"),
        "PYTHONNOUSERSITE": "1",
    }


def _run(script: Path, args: list[str], env: dict[str, str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
        **kwargs,
    )


def _install(env: dict[str, str], wheel: Path, digest: str, **extra_env: str):
    return _run(
        INSTALLER,
        ["--candidate", str(wheel), "--expected-sha256", digest],
        {**env, **extra_env},
    )


def _without_uv_bootstrap_environment(
    env: dict[str, str], tmp_path: Path, *, bad_checksum: bool = False,
) -> dict[str, str]:
    bin_dir = Path(env["PATH"].split(":", 1)[0])
    uv_stub = bin_dir / "uv"
    archive_root = tmp_path / "uv-x86_64-unknown-linux-gnu"
    archive_root.mkdir()
    shutil.copy2(uv_stub, archive_root / "uv")
    archive = tmp_path / "uv-x86_64-unknown-linux-gnu.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(archive_root / "uv", arcname="uv-x86_64-unknown-linux-gnu/uv")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = tmp_path / "uv.sha256"
    checksum.write_text(
        f"{'0' * 64 if bad_checksum else digest}  uv-x86_64-unknown-linux-gnu.tar.gz\n",
        encoding="ascii",
    )
    release_json = tmp_path / "uv-release.json"
    release_json.write_text(
        json.dumps(
            {
                "tag_name": "0.13.1",
                "assets": [
                    {
                        "name": "uv-x86_64-unknown-linux-gnu.tar.gz",
                        "browser_download_url": (
                            "https://github.com/astral-sh/uv/releases/download/0.13.1/"
                            "uv-x86_64-unknown-linux-gnu.tar.gz"
                        ),
                    },
                    {
                        "name": "uv-x86_64-unknown-linux-gnu.tar.gz.sha256",
                        "browser_download_url": (
                            "https://github.com/astral-sh/uv/releases/download/0.13.1/"
                            "uv-x86_64-unknown-linux-gnu.tar.gz.sha256"
                        ),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (bin_dir / "curl").write_text(
        "#!/bin/sh\n"
        "out=''\nwriteout=''\nurl=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -o) shift; out=\"$1\" ;;\n"
        "    -w) shift; writeout=\"$1\" ;;\n"
        "    *) url=\"$1\" ;;\n"
        "  esac\n"
        "  shift\n"
        "done\n"
        "case \"$url\" in\n"
        "  https://api.github.com/repos/astral-sh/uv/releases/latest) cp \"$FAKE_UV_RELEASE_JSON\" \"$out\"; status=200 ;;\n"
        "  https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-unknown-linux-gnu.tar.gz.sha256) cp \"$FAKE_UV_CHECKSUM\" \"$out\"; status=200 ;;\n"
        "  https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-unknown-linux-gnu.tar.gz) cp \"$FAKE_UV_ARCHIVE\" \"$out\"; status=200 ;;\n"
        "  *) printf '%s\\n' '{\"message\":\"Not Found\"}' > \"$out\"; status=404 ;;\n"
        "esac\n"
        "if [ \"$writeout\" = '%{http_code}' ]; then printf '%s' \"$status\"; fi\n",
        encoding="utf-8",
    )
    (bin_dir / "curl").chmod(0o755)
    python_wrapper = bin_dir / "python3"
    python_wrapper.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " \"$@\"\n",
        encoding="utf-8",
    )
    python_wrapper.chmod(0o755)
    uv_stub.unlink()
    return {
        **env,
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "FAKE_UV_RELEASE_JSON": str(release_json),
        "FAKE_UV_CHECKSUM": str(checksum),
        "FAKE_UV_ARCHIVE": str(archive),
    }


def test_linux_installer_and_uninstaller_have_valid_shell_syntax() -> None:
    for script in (INSTALLER, UNINSTALLER):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_help_is_available_without_linux_or_network() -> None:
    result = subprocess.run(["bash", str(INSTALLER), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--candidate" in result.stdout
    assert "--rollback" in result.stdout


def test_installer_fails_closed_when_no_published_release_exists(linux_shell: dict[str, str]) -> None:
    result = _run(INSTALLER, [], linux_shell)
    assert result.returncode != 0
    assert "no published stable release exists" in result.stderr
    assert not Path(linux_shell["LFL_HOME"]).exists()
    assert not (Path(linux_shell["HOME"]) / ".local/bin/lfl").exists()
    assert not list(Path(linux_shell["TMPDIR"]).glob("lfl-linux-install.*"))


def test_bad_candidate_digest_is_rejected_before_any_install_state(linux_shell: dict[str, str], tmp_path: Path) -> None:
    wheel = tmp_path / "llm_first_loop-0.6.31-py3-none-any.whl"
    _wheel(wheel, "0.6.31")
    result = _install(linux_shell, wheel, "0" * 64)
    assert result.returncode != 0
    assert "SHA-256 mismatch" in result.stderr
    assert not Path(linux_shell["LFL_HOME"]).exists()
    assert not (Path(linux_shell["HOME"]) / ".local/bin/lfl").exists()


def test_missing_uv_is_bootstrapped_from_official_release_with_verified_checksum(
    linux_shell: dict[str, str], tmp_path: Path,
) -> None:
    wheel = tmp_path / "llm_first_loop-0.6.31-py3-none-any.whl"
    digest = _wheel(wheel, "0.6.31")
    env = _without_uv_bootstrap_environment(linux_shell, tmp_path)

    result = _install(env, wheel, digest)

    assert result.returncode == 0, result.stderr
    root = Path(env["LFL_HOME"])
    assert (root / ".tools/uv").is_file()
    assert os.access(root / ".tools/uv", os.X_OK)
    assert (root / ".LFL-active-version").read_text(encoding="ascii").strip() == "0.6.31"
    assert not (root / ".linux-install.lock").exists()


def test_missing_uv_checksum_mismatch_fails_before_switch(linux_shell: dict[str, str], tmp_path: Path) -> None:
    wheel = tmp_path / "llm_first_loop-0.6.31-py3-none-any.whl"
    digest = _wheel(wheel, "0.6.31")
    env = _without_uv_bootstrap_environment(linux_shell, tmp_path, bad_checksum=True)

    result = _install(env, wheel, digest)

    root = Path(env["LFL_HOME"])
    assert result.returncode != 0
    assert "uv archive checksum mismatch" in result.stderr
    assert not (root / ".LFL-active-version").exists()
    assert not (root / "releases/LFL-0.6.31").exists()
    assert not (root / ".linux-install.lock").exists()


def test_unsupported_architecture_is_rejected_without_mutation(linux_shell: dict[str, str]) -> None:
    result = _run(INSTALLER, [], {**linux_shell, "FAKE_UNAME_M": "armv7l"})
    assert result.returncode != 0
    assert "unsupported CPU architecture" in result.stderr
    assert not Path(linux_shell["LFL_HOME"]).exists()


def test_musl_or_unknown_libc_is_rejected_without_mutation(linux_shell: dict[str, str]) -> None:
    result = _run(INSTALLER, [], {**linux_shell, "FAKE_GLIBC_VERSION": "musl libc"})
    assert result.returncode != 0
    assert "supports glibc-based Linux" in result.stderr
    assert not Path(linux_shell["LFL_HOME"]).exists()


@pytest.mark.skipif(
    env_channel.nested_sandbox_exec(),
    reason="环境受限：安装脚本 spawn 子进程链在嵌套 sandbox-exec 通道受限【RED-10】",
)
def test_install_upgrade_rollback_failed_upgrade_and_uninstall_preserve_user_data(
    linux_shell: dict[str, str], tmp_path: Path,
) -> None:
    env = linux_shell
    root = Path(env["LFL_HOME"])
    home = Path(env["HOME"])
    wheel31 = tmp_path / "llm_first_loop-0.6.31-py3-none-any.whl"
    wheel32 = tmp_path / "llm_first_loop-0.6.32-py3-none-any.whl"
    wheel33 = tmp_path / "llm_first_loop-0.6.33-py3-none-any.whl"
    sha31, sha32, sha33 = _wheel(wheel31, "0.6.31"), _wheel(wheel32, "0.6.32"), _wheel(wheel33, "0.6.33")

    first = _install(env, wheel31, sha31)
    assert first.returncode == 0, first.stderr
    active = root / ".LFL-active-version"
    previous = root / ".LFL-previous-version"
    launcher = home / ".local/bin/lfl"
    assert active.read_text().strip() == "0.6.31"
    assert not previous.exists()
    assert subprocess.run([str(launcher), "--version"], env={**os.environ, **env}, text=True, capture_output=True).stdout.strip() == "llm-first-loop 0.6.31"

    busy = _install(
        env, wheel32, sha32,
        FAKE_PS_LINES=f"4242 {root}/releases/LFL-0.6.31/venv/bin/python -m llm_loop.web",
    )
    assert busy.returncode != 0
    assert "process is still running" in busy.stderr
    assert active.read_text().strip() == "0.6.31"
    assert not (root / "releases/LFL-0.6.32").exists()

    second = _install(env, wheel32, sha32)
    assert second.returncode == 0, second.stderr
    assert active.read_text().strip() == "0.6.32"
    assert previous.read_text().strip() == "0.6.31"
    assert (root / "releases/LFL-0.6.31/venv/bin/lfl").is_file()

    failed = _install(env, wheel33, sha33, FAKE_UV_FAIL_VERSION="0.6.33")
    assert failed.returncode != 0
    assert active.read_text().strip() == "0.6.32"
    assert previous.read_text().strip() == "0.6.31"
    assert not (root / "releases/LFL-0.6.33").exists()
    assert not (root / ".linux-install.lock").exists()

    # Rollback must remain available even when the active release is broken.
    (root / "releases/LFL-0.6.32/venv/bin/lfl").unlink()
    rollback = _run(INSTALLER, ["--rollback"], env)
    assert rollback.returncode == 0, rollback.stderr
    assert active.read_text().strip() == "0.6.31"
    assert previous.read_text().strip() == "0.6.32"
    assert subprocess.run([str(launcher), "--version"], env={**os.environ, **env}, text=True, capture_output=True).stdout.strip() == "llm-first-loop 0.6.31"

    config = root / ".env"
    data_file = root / "data/session.jsonl"
    method_file = root / "data/methods/example.json"
    config.write_text("LLM_MODEL=test-model\n", encoding="utf-8")
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text('{"session":"keep"}\n', encoding="utf-8")
    method_file.parent.mkdir(parents=True, exist_ok=True)
    method_file.write_text('{"method":"keep"}\n', encoding="utf-8")

    busy_uninstall = _run(
        UNINSTALLER, ["--yes"],
        {**env, "FAKE_PS_LINES": f"4242 {root}/releases/LFL-0.6.31/venv/bin/python -m llm_loop.web"},
    )
    assert busy_uninstall.returncode != 0
    assert "process is still running" in busy_uninstall.stderr
    assert active.read_text().strip() == "0.6.31"
    assert config.exists() and data_file.exists() and method_file.exists()

    removed = _run(UNINSTALLER, ["--yes"], env)
    assert removed.returncode == 0, removed.stderr
    assert not launcher.exists()
    assert not (root / "releases").exists()
    assert not active.exists() and not previous.exists()
    assert config.read_text(encoding="utf-8") == "LLM_MODEL=test-model\n"
    assert data_file.read_text(encoding="utf-8") == '{"session":"keep"}\n'
    assert method_file.read_text(encoding="utf-8") == '{"method":"keep"}\n'



@pytest.mark.skipif(
    env_channel.nested_sandbox_exec(),
    reason="环境受限：安装脚本 spawn 子进程链在嵌套 sandbox-exec 通道受限【RED-11】",
)
def test_active_pointer_write_failure_restores_both_version_pointers(
    linux_shell: dict[str, str], tmp_path: Path,
) -> None:
    env = linux_shell
    root = Path(env["LFL_HOME"])
    wheel30 = tmp_path / "llm_first_loop-0.6.30-py3-none-any.whl"
    wheel31 = tmp_path / "llm_first_loop-0.6.31-py3-none-any.whl"
    wheel32 = tmp_path / "llm_first_loop-0.6.32-py3-none-any.whl"
    sha30, sha31, sha32 = _wheel(wheel30, "0.6.30"), _wheel(wheel31, "0.6.31"), _wheel(wheel32, "0.6.32")

    first = _install(env, wheel30, sha30)
    assert first.returncode == 0, first.stderr
    second = _install(env, wheel31, sha31)
    assert second.returncode == 0, second.stderr

    active = root / ".LFL-active-version"
    previous = root / ".LFL-previous-version"
    assert active.read_text(encoding="ascii").strip() == "0.6.31"
    assert previous.read_text(encoding="ascii").strip() == "0.6.30"

    # Fail once immediately before the active pointer's atomic replace.
    real_python = shutil.which("python3")
    assert real_python is not None
    bin_dir = Path(env["PATH"].split(":", 1)[0])
    fail_once = tmp_path / "fail-active-pointer-once"
    python_wrapper = bin_dir / "python3"
    python_wrapper.write_text(
        "#!/bin/sh\n"
        "if [ -n \"${FAIL_ACTIVE_POINTER_ONCE:-}\" ] && [ \"${1:-}\" = '-' ] && [ \"$#\" -ge 4 ] && [ \"${3:-}\" = \"$LFL_HOME/.LFL-active-version\" ] && [ ! -e \"$FAIL_ACTIVE_POINTER_ONCE\" ]; then\n"
        "  : > \"$FAIL_ACTIVE_POINTER_ONCE\"\n"
        "  cat >/dev/null\n"
        "  printf '%s\\n' 'injected active pointer write failure' >&2\n"
        "  exit 91\n"
        "fi\n"
        f"exec {shlex.quote(real_python)} \"$@\"\n",
        encoding="utf-8",
    )
    python_wrapper.chmod(0o755)
    failed = _install(env, wheel32, sha32, FAIL_ACTIVE_POINTER_ONCE=str(fail_once))

    assert failed.returncode != 0
    assert "injected active pointer write failure" in failed.stderr
    assert active.read_text(encoding="ascii").strip() == "0.6.31"
    assert previous.read_text(encoding="ascii").strip() == "0.6.30"
    # The fully built but inactive release may remain available for a retry.
    assert (root / "releases/LFL-0.6.32").is_dir()
    assert not (root / "releases/LFL-0.6.32/.installer-incomplete").exists()
    assert not (root / ".linux-install.lock").exists()

def test_uninstaller_refuses_unmanaged_launcher_without_deleting_data(linux_shell: dict[str, str]) -> None:
    env = linux_shell
    root = Path(env["LFL_HOME"])
    root.mkdir(parents=True)
    config = root / ".env"
    config.write_text("preserve=yes\n", encoding="utf-8")
    launcher = Path(env["HOME"]) / ".local/bin/lfl"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\necho unrelated\n", encoding="utf-8")
    result = _run(UNINSTALLER, ["--yes"], env)
    assert result.returncode != 0
    assert "unmanaged launcher" in result.stderr
    assert config.read_text(encoding="utf-8") == "preserve=yes\n"
    assert launcher.exists()


def test_github_release_checksums_have_bare_asset_names_consumable_by_installer(tmp_path: Path) -> None:
    """Actual release.yml checksum step must match the public installer's exact wheel-name check.

    v0.6.33 generated ``dist/wheel.whl`` in SHA256SUMS; published assets instead
    expose ``wheel.whl`` at the release root. A local-wheel-only smoke missed it.
    """
    import re

    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    expected_prefix = "run: cd dist && sha256sum * > SHA256SUMS && sha256sum --check SHA256SUMS"
    matching = [line.strip() for line in workflow.splitlines() if line.strip().startswith("run: cd dist && sha256sum")]
    assert matching == [expected_prefix], "release checksums must use names relative to the download directory"
    assert "match.group(2) == sys.argv[2]" in INSTALLER.read_text(encoding="utf-8"), "installer parser contract changed"

    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "llm_first_loop-0.6.34-py3-none-any.whl"
    wheel.write_bytes(b"stable-public-release-wheel-fixture")
    (dist / "install_linux.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    workflow_command = matching[0].removeprefix("run: ")
    if shutil.which("sha256sum") is None:
        assert shutil.which("shasum") is not None, "a SHA-256 utility is required for the contract check"
        workflow_command = workflow_command.replace("sha256sum", "shasum -a 256")
    completed = subprocess.run(["bash", "-c", workflow_command], cwd=tmp_path, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    manifest = (dist / "SHA256SUMS").read_text(encoding="utf-8")
    entries = [re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+?)\s*", line) for line in manifest.splitlines()]
    assert entries and all(entries)
    items = [(entry.group(2), entry.group(1).lower()) for entry in entries if entry is not None]
    assert len([digest for name, digest in items if name == wheel.name]) == 1
    assert dict(items)[wheel.name] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert all("/" not in name and "\\" not in name for name, _ in items)

    # softprops/action-gh-release accepts dotfiles in dist/* (observed:
    # Draft v0.6.33 contained a spurious 1-byte default.gitignore absent from
    # SHA256SUMS). Whitelist exactly the required release assets instead.
    assert "          files: |\n" in workflow
    asset_lines = workflow.split("          files: |\n", 1)[1].splitlines()
    assert {line.strip() for line in asset_lines if line.strip()} == {
        "dist/llm_first_loop-*.whl",
        "dist/llm_first_loop-*.tar.gz",
        "dist/install_linux.sh",
        "dist/uninstall_linux.sh",
        "dist/installation-smoke.json",
        "dist/linux-installer-smoke.json",
        "dist/SHA256SUMS",
    }, "Release asset scope must exclude hidden/unchecksummed files"


def test_github_ci_runs_linux_installer_on_native_x86_64_and_aarch64() -> None:
    """An x86-only CI result must never be presented as ARM64 native coverage."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    linux_job = workflow.split("  linux-installer:\n", 1)[1].split("\n  nightly-real:\n", 1)[0]
    assert "      fail-fast: false\n" in linux_job
    assert "          - os: ubuntu-24.04\n            arch: x86_64\n" in linux_job
    assert "          - os: ubuntu-24.04-arm\n            arch: aarch64\n" in linux_job
    assert "    runs-on: ${{ matrix.os }}\n" in linux_job
    assert 'test "$(uname -m)" = "${{ matrix.arch }}"' in linux_job
    assert "getconf GNU_LIBC_VERSION | grep -q '^glibc '" in linux_job
    assert "python scripts/verify_linux_installer.py --wheel dist/*.whl --report dist/linux-installer-smoke.json" in linux_job
    assert "name: linux-installer-smoke-${{ matrix.arch }}" in linux_job
