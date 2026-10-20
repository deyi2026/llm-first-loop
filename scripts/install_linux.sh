#!/usr/bin/env bash
# LFL Linux user-level installer. No sudo, system service, or user-data deletion.
set -Eeuo pipefail
umask 077

readonly REPO_OWNER="deyi2026"
readonly REPO_NAME="llm-first-loop"
readonly API_ROOT="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}"

usage() {
  cat <<'EOF'
LFL Linux installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/deyi2026/llm-first-loop/main/scripts/install_linux.sh -o lfl-install.sh && bash lfl-install.sh
  bash install_linux.sh --version 0.6.35
  bash install_linux.sh --candidate ./llm_first_loop-0.6.35-py3-none-any.whl --expected-sha256 SHA256
  bash install_linux.sh --rollback

Options:
  --version VERSION                 Install a published stable release; use an installed version offline.
  --candidate FILE --expected-sha256 SHA256
                                    Install a local wheel after verifying its exact SHA-256.
  --rollback                        Switch back to the previous retained release, without network access.
  -h, --help                        Show this help.
EOF
}

die() {
  printf 'LFL installer: %s\n' "$*" >&2
  exit 1
}

valid_version() {
  [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

MODE="latest"
REQUESTED_VERSION=""
CANDIDATE=""
EXPECTED_SHA=""
while (($#)); do
  case "$1" in
    --version)
      (($# >= 2)) || die "--version requires a version"
      [[ "$MODE" == "latest" && -z "$CANDIDATE" ]] || die "--version cannot be combined with another install mode"
      MODE="version"
      REQUESTED_VERSION="${2#v}"
      shift 2
      ;;
    --candidate)
      (($# >= 2)) || die "--candidate requires a wheel path"
      [[ "$MODE" == "latest" && -z "$CANDIDATE" ]] || die "--candidate cannot be combined with another install mode"
      MODE="candidate"
      CANDIDATE="$2"
      shift 2
      ;;
    --expected-sha256)
      (($# >= 2)) || die "--expected-sha256 requires a SHA-256 digest"
      EXPECTED_SHA="$2"
      shift 2
      ;;
    --rollback)
      [[ "$MODE" == "latest" && -z "$CANDIDATE" ]] || die "--rollback cannot be combined with an install mode"
      MODE="rollback"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *) die "unknown option: $1 (use --help)" ;;
  esac
done

[[ "$(uname -s)" == "Linux" ]] || die "Linux only; no files were changed"
case "$(uname -m)" in
  x86_64|aarch64) ;;
  *) die "unsupported CPU architecture: $(uname -m); supported: x86_64 and aarch64" ;;
esac
command -v getconf >/dev/null 2>&1 || die "getconf is required to identify the Linux C library"
LIBC_VERSION="$(getconf GNU_LIBC_VERSION 2>/dev/null || true)"
[[ "$LIBC_VERSION" == glibc\ * ]] || die "this installer currently supports glibc-based Linux (for example Ubuntu/Debian), not musl/unknown libc"
[[ "$(id -u)" != "0" ]] || die "run as a normal user, not root; sudo is not required"
[[ -n "${HOME:-}" && "$HOME" == /* && -d "$HOME" ]] || die "HOME must be an existing absolute directory"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required for release metadata; Python 3.13 is installed by uv"

if [[ -n "$REQUESTED_VERSION" ]] && ! valid_version "$REQUESTED_VERSION"; then
  die "invalid version '$REQUESTED_VERSION'; expected MAJOR.MINOR.PATCH"
fi
if [[ "$MODE" == "candidate" ]]; then
  [[ -n "$EXPECTED_SHA" && "$EXPECTED_SHA" =~ ^[0-9a-fA-F]{64}$ ]] || die "--candidate requires a 64-character --expected-sha256"
elif [[ -n "$EXPECTED_SHA" ]]; then
  die "--expected-sha256 is only valid with --candidate"
fi

if [[ -n "${LFL_HOME:-}" ]]; then
  ROOT_INPUT="$LFL_HOME"
elif [[ -n "${XDG_DATA_HOME:-}" && "$XDG_DATA_HOME" == /* ]]; then
  ROOT_INPUT="$XDG_DATA_HOME/lfl"
else
  ROOT_INPUT="$HOME/.local/share/lfl"
fi
ROOT="$(python3 - "$ROOT_INPUT" <<'PY'
import os, sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
)"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/lfl"
RELEASES="$ROOT/releases"
ACTIVE_FILE="$ROOT/.LFL-active-version"
PREVIOUS_FILE="$ROOT/.LFL-previous-version"
LOCK_DIR="$ROOT/.linux-install.lock"
LEGACY_LAUNCHER="$ROOT/.linux-legacy-lfl-launcher"

if [[ "$MODE" == "rollback" ]]; then
  [[ -d "$ROOT" && ! -L "$ROOT" ]] || die "no managed LFL install found at $ROOT"
elif [[ -e "$ROOT" || -L "$ROOT" ]]; then
  [[ -d "$ROOT" && ! -L "$ROOT" ]] || die "LFL_HOME must be a real directory, not a symlink or non-directory: $ROOT"
fi

LAUNCHER_KIND="none"
if [[ -e "$LAUNCHER" || -L "$LAUNCHER" ]]; then
  if [[ -f "$LAUNCHER" && ! -L "$LAUNCHER" ]] && grep -Fqx '# LFL_LINUX_LAUNCHER_V1' "$LAUNCHER"; then
    grep -Fqx "# LFL_LINUX_INSTALL_ROOT: $ROOT" "$LAUNCHER" || die "$LAUNCHER belongs to a different LFL_HOME; set the original LFL_HOME to upgrade it"
    LAUNCHER_KIND="managed"
  elif [[ -L "$LAUNCHER" ]]; then
    LEGACY_TARGET="$(readlink -f "$LAUNCHER" 2>/dev/null || true)"
    case "$LEGACY_TARGET" in
      */uv/tools/llm-first-loop/*) LAUNCHER_KIND="legacy-uv" ;;
      *) die "refusing to overwrite an unmanaged launcher at $LAUNCHER" ;;
    esac
  else
    die "refusing to overwrite an unmanaged file at $LAUNCHER"
  fi
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lfl-linux-install.XXXXXX")"
chmod 700 "$TMP_DIR"
NEW_RELEASE_DIR=""
LOCK_HELD="0"
LAUNCHER_CREATED="0"
LEGACY_BACKUP_CREATED="0"
POINTER_TRANSACTION_STARTED="0"
POINTER_ACTIVE_ATTEMPTED="0"
POINTER_PREVIOUS_ATTEMPTED="0"
cleanup() {
  local rc=$?
  if [[ -n "$NEW_RELEASE_DIR" && -f "$NEW_RELEASE_DIR/.installer-incomplete" ]]; then
    local active="" previous=""
    [[ ! -f "$ACTIVE_FILE" ]] || active="$(cat "$ACTIVE_FILE" 2>/dev/null || true)"
    [[ ! -f "$PREVIOUS_FILE" ]] || previous="$(cat "$PREVIOUS_FILE" 2>/dev/null || true)"
    local incomplete_version="${NEW_RELEASE_DIR##*/LFL-}"
    if [[ "$active" != "$incomplete_version" && "$previous" != "$incomplete_version" ]]; then
      python3 - "$NEW_RELEASE_DIR" "$ROOT/releases" <<'PY'
import os, shutil, sys
target, parent = map(os.path.abspath, sys.argv[1:])
if os.path.dirname(target) == parent and os.path.basename(target).startswith("LFL-"):
    shutil.rmtree(target)
PY
    fi
  fi
  if [[ "$rc" != "0" && "$POINTER_TRANSACTION_STARTED" == "1" ]]; then
    local restore_failed="0"
    if [[ "$POINTER_ACTIVE_ATTEMPTED" == "1" ]]; then
      if [[ -n "${CURRENT_VERSION:-}" ]]; then
        write_pointer "$ACTIVE_FILE" "$CURRENT_VERSION" || restore_failed="1"
      else
        rm -f -- "$ACTIVE_FILE" || restore_failed="1"
      fi
    fi
    if [[ "$POINTER_PREVIOUS_ATTEMPTED" == "1" ]]; then
      if [[ -n "${OLD_PREVIOUS:-}" ]]; then
        write_pointer "$PREVIOUS_FILE" "$OLD_PREVIOUS" || restore_failed="1"
      else
        rm -f -- "$PREVIOUS_FILE" || restore_failed="1"
      fi
    fi
    if [[ "$restore_failed" == "1" ]]; then
      printf 'LFL installer: pointer transaction failed and automatic pointer restoration was incomplete; inspect %s and %s\n' "$ACTIVE_FILE" "$PREVIOUS_FILE" >&2
    fi
  fi
  if [[ "$rc" != "0" && "$LAUNCHER_CREATED" == "1" ]]; then
    rm -f -- "$LAUNCHER"
  fi
  if [[ "$rc" != "0" && "$LEGACY_BACKUP_CREATED" == "1" && -L "$LEGACY_LAUNCHER" ]]; then
    rm -f -- "$LAUNCHER"
    mv -- "$LEGACY_LAUNCHER" "$LAUNCHER" 2>/dev/null || true
  fi
  python3 - "$TMP_DIR" <<'PY'
import os, shutil, sys
path = os.path.abspath(sys.argv[1])
if os.path.basename(path).startswith("lfl-linux-install.") and os.path.dirname(path) == os.path.abspath(os.environ.get("TMPDIR", "/tmp")):
    shutil.rmtree(path)
PY
  # Keep the lock until every failure-cleanup mutation is complete.
  if [[ "$LOCK_HELD" == "1" ]]; then
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
  return "$rc"
}
trap cleanup EXIT

read_pointer() {
  python3 - "$ROOT" "$1" <<'PY'
import os, re, sys
root, path = map(os.path.abspath, sys.argv[1:])
if os.path.dirname(path) != root or os.path.basename(path) not in {".LFL-active-version", ".LFL-previous-version"}:
    raise SystemExit("unsafe version pointer path")
if os.path.islink(path):
    raise SystemExit("refusing symlinked version pointer: " + path)
if not os.path.isfile(path):
    raise SystemExit(1)
with open(path, encoding="ascii") as stream:
    value = stream.read()
match = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+)\n?", value)
if not match:
    raise SystemExit("invalid version pointer in " + path)
print(match.group(1), end="")
PY
}

write_pointer() {
  python3 - "$ROOT" "$1" "$2" <<'PY'
import os, re, tempfile, sys
root, target, value = sys.argv[1:]
root, target = map(os.path.abspath, (root, target))
if os.path.islink(root) or not os.path.isdir(root):
    raise SystemExit("unsafe LFL_HOME while updating version pointer")
if os.path.dirname(target) != root or os.path.basename(target) not in {".LFL-active-version", ".LFL-previous-version"}:
    raise SystemExit("unsafe version pointer path")
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
    raise SystemExit("refusing invalid version pointer value")
if os.path.islink(target) or (os.path.lexists(target) and not os.path.isfile(target)):
    raise SystemExit("refusing unsafe version pointer target")
fd, temporary = tempfile.mkstemp(prefix=".pointer.", dir=root)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(value + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}

check_json_ok() {
  python3 -c 'import json,sys; value=json.load(sys.stdin); sys.exit(0 if value.get("ok") is True else 1)'
}

wheel_version() {
  python3 - "$1" <<'PY'
import email, re, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
    if len(names) != 1:
        raise SystemExit("wheel must contain exactly one dist-info/METADATA")
    metadata = email.message_from_bytes(archive.read(names[0]))
    name = (metadata.get("Name") or "").lower().replace("_", "-")
    version = metadata.get("Version") or ""
    if name != "llm-first-loop" or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise SystemExit("wheel must be llm-first-loop with a stable MAJOR.MINOR.PATCH version")
    print(version)
PY
}

verify_release_dir() {
  local directory="$1" version="$2" allow_incomplete="${3:-0}" output
  [[ -d "$directory" && ! -L "$directory" ]] || die "release directory is missing or unsafe: $directory"
  if [[ -f "$directory/.installer-incomplete" && "$allow_incomplete" != "1" ]]; then
    die "incomplete release found at $directory"
  fi
  [[ -f "$directory/.installer-wheel.sha256" && ! -L "$directory/.installer-wheel.sha256" ]] || die "release integrity record missing: $directory"
  (cd "$directory" && sha256sum --check --status .installer-wheel.sha256) || die "retained wheel checksum failed for LFL $version"
  [[ -x "$directory/venv/bin/lfl" && -x "$directory/venv/bin/python" ]] || die "release executable missing: $directory"
  output="$(env LFL_HOME="$ROOT" PYTHONNOUSERSITE=1 "$directory/venv/bin/lfl" --version 2>&1)" || die "release version check failed: $output"
  [[ "$output" == *"$version"* ]] || die "release reports unexpected version (expected $version): $output"
  output="$(env LFL_HOME="$ROOT" PYTHONNOUSERSITE=1 "$directory/venv/bin/lfl" check-install 2>&1)" || die "release resource check failed: $output"
  printf '%s' "$output" | check_json_ok || die "release resource check did not report ok=true: $output"
}

assert_no_managed_lfl_processes() {
  local process_list line pid
  command -v ps >/dev/null 2>&1 || die "cannot verify running LFL processes because ps is unavailable; stop them manually before upgrading"
  process_list="$(ps -eo pid=,args=)" || die "cannot verify running LFL processes; stop them manually before upgrading"
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    pid="${line#"${line%%[![:space:]]*}"}"
    pid="${pid%%[[:space:]]*}"
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    [[ "$pid" != "$$" && "$pid" != "$PPID" ]] || continue
    case "$line" in
      *"$ROOT/releases/LFL-"*"/venv/bin/"*|*"/uv/tools/llm-first-loop/"*)
        die "an LFL process is still running (pid $pid); stop it before upgrading or rolling back"
        ;;
    esac
  done <<< "$process_list"
}

resolve_release() {
  local api_url="$1" requested="$2" http_code metadata json_path
  command -v curl >/dev/null 2>&1 || die "curl is required to download a published release"
  json_path="$TMP_DIR/release.json"
  http_code="$(curl -sSL --proto '=https' --proto-redir '=https' --tlsv1.2 --max-time 30 -o "$json_path" -w '%{http_code}' "$api_url")" || die "could not reach the official GitHub release API"
  if [[ "$http_code" != "200" ]]; then
    if [[ "$http_code" == "404" ]]; then
      if [[ -n "$requested" ]]; then die "no published stable release v$requested exists yet; no files were changed"; fi
      die "no published stable release exists yet; drafts are not installable, and no files were changed"
    fi
    die "GitHub release API returned HTTP $http_code; no files were changed"
  fi
  metadata="$(python3 - "$json_path" "$requested" <<'PY'
import json, re, sys
with open(sys.argv[1], encoding="utf-8") as f:
    release = json.load(f)
requested = sys.argv[2]
tag = release.get("tag_name", "")
if release.get("draft") or release.get("prerelease"):
    raise SystemExit("refusing draft or prerelease release")
version = tag[1:] if tag.startswith("v") else tag
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
    raise SystemExit("release tag is not a stable MAJOR.MINOR.PATCH version")
if requested and version != requested:
    raise SystemExit("release tag does not match requested version")
wheel = f"llm_first_loop-{version}-py3-none-any.whl"
assets = {a.get("name"): a.get("browser_download_url", "") for a in release.get("assets", [])}
base = f"https://github.com/deyi2026/llm-first-loop/releases/download/{tag}/"
wheel_url, sums_url = assets.get(wheel, ""), assets.get("SHA256SUMS", "")
if not wheel_url.startswith(base) or not sums_url.startswith(base):
    raise SystemExit("official release is missing the expected wheel or SHA256SUMS asset")
print("\t".join((version, wheel_url, sums_url)))
PY
)" || die "release metadata is invalid or missing the expected wheel/SHA256SUMS"
  IFS=$'\t' read -r RELEASE_VERSION WHEEL_URL SUMS_URL <<< "$metadata"
  [[ -n "$RELEASE_VERSION" && -n "$WHEEL_URL" && -n "$SUMS_URL" ]] || die "could not parse official release metadata"
  WHEEL_NAME="llm_first_loop-${RELEASE_VERSION}-py3-none-any.whl"
  curl -fLsS --proto '=https' --proto-redir '=https' --tlsv1.2 --max-time 120 "$SUMS_URL" -o "$TMP_DIR/SHA256SUMS" || die "could not download release SHA256SUMS"
  EXPECTED_SHA="$(python3 - "$TMP_DIR/SHA256SUMS" "$WHEEL_NAME" <<'PY'
import re, sys
matches = []
for line in open(sys.argv[1], encoding="utf-8"):
    match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+?)\s*", line.rstrip("\n"))
    if match and match.group(2) == sys.argv[2]:
        matches.append(match.group(1).lower())
if len(matches) != 1:
    raise SystemExit("SHA256SUMS must contain exactly one entry for the release wheel")
print(matches[0])
PY
)" || die "could not read the release wheel checksum"
  WHEEL_PATH="$TMP_DIR/$WHEEL_NAME"
  curl -fLsS --proto '=https' --proto-redir '=https' --tlsv1.2 --max-time 600 "$WHEEL_URL" -o "$WHEEL_PATH" || die "could not download release wheel"
  SOURCE_DESCRIPTION="release:$RELEASE_VERSION"
}

bootstrap_uv() {
  local uv_bin asset asset_dir metadata http_code expected actual uv_tmp
  uv_bin="$(command -v uv || true)"
  if [[ -n "$uv_bin" ]]; then
    printf '%s' "$uv_bin"
    return 0
  fi
  if [[ -x "$ROOT/.tools/uv" && ! -L "$ROOT/.tools/uv" ]]; then
    printf '%s' "$ROOT/.tools/uv"
    return 0
  fi
  command -v curl >/dev/null 2>&1 || die "curl is required to download the official uv runtime"
  [[ ! -e "$ROOT/.tools/uv" && ! -L "$ROOT/.tools/uv" ]] || die "refusing to overwrite an unsafe existing uv bootstrap"
  case "$(uname -m)" in
    x86_64) asset="uv-x86_64-unknown-linux-gnu.tar.gz"; asset_dir="uv-x86_64-unknown-linux-gnu" ;;
    aarch64) asset="uv-aarch64-unknown-linux-gnu.tar.gz"; asset_dir="uv-aarch64-unknown-linux-gnu" ;;
    *) die "cannot bootstrap uv for architecture $(uname -m)" ;;
  esac
  http_code="$(curl -sSL --proto '=https' --proto-redir '=https' --tlsv1.2 --max-time 30 -o "$TMP_DIR/uv-release.json" -w '%{http_code}' https://api.github.com/repos/astral-sh/uv/releases/latest)" || die "could not reach the official uv release API"
  [[ "$http_code" == "200" ]] || die "official uv release API returned HTTP $http_code"
  metadata="$(python3 - "$TMP_DIR/uv-release.json" "$asset" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    release = json.load(f)
tag = release.get("tag_name", "")
base = f"https://github.com/astral-sh/uv/releases/download/{tag}/"
assets = {a.get("name"): a.get("browser_download_url", "") for a in release.get("assets", [])}
name = sys.argv[2]
archive, checksum = assets.get(name, ""), assets.get(name + ".sha256", "")
if not archive.startswith(base) or not checksum.startswith(base):
    raise SystemExit("official uv release is missing the archive or SHA-256 asset")
print("\t".join((archive, checksum)))
PY
)" || die "could not resolve the official uv Linux binary"
  IFS=$'\t' read -r archive_url checksum_url <<< "$metadata"
  curl -fLsS --proto '=https' --proto-redir '=https' --tlsv1.2 --max-time 120 "$checksum_url" -o "$TMP_DIR/uv.sha256" || die "could not download uv checksum"
  expected="$(python3 - "$TMP_DIR/uv.sha256" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r"\b([0-9a-fA-F]{64})\b", text)
if not match:
    raise SystemExit("uv checksum asset did not contain a SHA-256 digest")
print(match.group(1).lower())
PY
)" || die "could not parse uv checksum"
  curl -fLsS --proto '=https' --proto-redir '=https' --tlsv1.2 --max-time 120 "$archive_url" -o "$TMP_DIR/uv.tar.gz" || die "could not download the official uv binary"
  actual="$(sha256sum "$TMP_DIR/uv.tar.gz" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || die "official uv archive checksum mismatch"
  if [[ -e "$ROOT/.tools" || -L "$ROOT/.tools" ]]; then
    [[ -d "$ROOT/.tools" && ! -L "$ROOT/.tools" ]] || die "refusing to write uv into an unsafe .tools path"
  else
    mkdir -m 700 -- "$ROOT/.tools"
  fi
  [[ ! -e "$ROOT/.tools/uv" && ! -L "$ROOT/.tools/uv" ]] || die "uv destination already exists; refusing to overwrite it"
  uv_tmp="$TMP_DIR/uv.new"
  tar -xOzf "$TMP_DIR/uv.tar.gz" "$asset_dir/uv" > "$uv_tmp" || die "could not extract the uv executable"
  chmod 755 "$uv_tmp"
  mv -- "$uv_tmp" "$ROOT/.tools/uv"
  printf '%s' "$ROOT/.tools/uv"
}

install_launcher() {
  local launcher_temp
  if [[ "$LAUNCHER_KIND" == "managed" ]]; then
    return 0
  fi
  mkdir -p -- "$BIN_DIR"
  if [[ "$LAUNCHER_KIND" == "legacy-uv" ]]; then
    [[ ! -e "$LEGACY_LAUNCHER" && ! -L "$LEGACY_LAUNCHER" ]] || die "legacy launcher backup already exists; refusing to overwrite it"
    "$LAUNCHER" --version >/dev/null 2>&1 || die "existing uv tool launcher does not run; refusing automatic migration"
    "$LAUNCHER" check-install >/dev/null 2>&1 || die "existing uv tool installation failed check-install; refusing automatic migration"
    cp -P -- "$LAUNCHER" "$LEGACY_LAUNCHER"
    LEGACY_BACKUP_CREATED="1"
  fi
  launcher_temp="$BIN_DIR/.lfl-installer-$$"
  python3 - "$ROOT" "$launcher_temp" <<'PY'
import os, shlex, sys
root, path = sys.argv[1:]
quoted = shlex.quote(root)
text = f'''#!/bin/sh
# LFL_LINUX_LAUNCHER_V1
# LFL_LINUX_INSTALL_ROOT: {root}
set -eu
INSTALL_ROOT={quoted}
ACTIVE_FILE="$INSTALL_ROOT/.LFL-active-version"
if [ ! -f "$ACTIVE_FILE" ]; then
  echo "LFL is not fully installed. Re-run the official Linux installer." >&2
  exit 1
fi
IFS= read -r VERSION < "$ACTIVE_FILE" || true
case "$VERSION" in
  ''|*[!0-9.]* ) echo "LFL active-version pointer is invalid." >&2; exit 1 ;;
esac
APP="$INSTALL_ROOT/releases/LFL-$VERSION"
if [ ! -x "$APP/venv/bin/lfl" ]; then
  echo "LFL release $VERSION is incomplete. Use the official installer or --rollback." >&2
  exit 1
fi
exec "$APP/venv/bin/lfl" "$@"
'''
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
os.chmod(path, 0o755)
PY
  mv -f -- "$launcher_temp" "$LAUNCHER"
  if [[ "$LAUNCHER_KIND" == "none" ]]; then
    LAUNCHER_CREATED="1"
  fi
}

if [[ "$MODE" == "candidate" ]]; then
  [[ -f "$CANDIDATE" && ! -L "$CANDIDATE" ]] || die "candidate must be a regular non-symlink wheel file"
  CANDIDATE="$(python3 - "$CANDIDATE" <<'PY'
import os, sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
)"
  RELEASE_VERSION="$(wheel_version "$CANDIDATE")" || die "candidate wheel metadata is invalid"
  valid_version "$RELEASE_VERSION" || die "candidate wheel version is invalid"
  WHEEL_NAME="llm_first_loop-${RELEASE_VERSION}-py3-none-any.whl"
  WHEEL_PATH="$TMP_DIR/$WHEEL_NAME"
  cp -- "$CANDIDATE" "$WHEEL_PATH"
  EXPECTED_SHA="$(printf '%s' "$EXPECTED_SHA" | tr '[:upper:]' '[:lower:]')"
  ACTUAL_SHA="$(sha256sum "$WHEEL_PATH" | awk '{print $1}')"
  [[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || die "candidate SHA-256 mismatch; no active version was changed"
  SOURCE_DESCRIPTION="local-candidate"
elif [[ "$MODE" == "version" && -d "$RELEASES/LFL-$REQUESTED_VERSION" && -f "$RELEASES/LFL-$REQUESTED_VERSION/.installer-wheel.sha256" ]]; then
  RELEASE_VERSION="$REQUESTED_VERSION"
  WHEEL_NAME="llm_first_loop-${RELEASE_VERSION}-py3-none-any.whl"
  EXPECTED_SHA="$(awk 'NR==1 {print $1}' "$RELEASES/LFL-$RELEASE_VERSION/.installer-wheel.sha256")"
  [[ "$EXPECTED_SHA" =~ ^[0-9a-f]{64}$ ]] || die "retained release checksum is invalid"
  SOURCE_DESCRIPTION="retained-release"
  REUSE_LOCAL_RELEASE="1"
elif [[ "$MODE" == "version" ]]; then
  resolve_release "$API_ROOT/releases/tags/v$REQUESTED_VERSION" "$REQUESTED_VERSION"
  REUSE_LOCAL_RELEASE="0"
elif [[ "$MODE" == "latest" ]]; then
  resolve_release "$API_ROOT/releases/latest" ""
  REUSE_LOCAL_RELEASE="0"
fi

if [[ "$MODE" != "rollback" ]]; then
  valid_version "$RELEASE_VERSION" || die "resolved release version is invalid"
  if [[ "${REUSE_LOCAL_RELEASE:-0}" != "1" ]]; then
    ACTUAL_SHA="$(sha256sum "$WHEEL_PATH" | awk '{print $1}')"
    [[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || die "release wheel SHA-256 mismatch; no active version was changed"
    [[ "$(wheel_version "$WHEEL_PATH")" == "$RELEASE_VERSION" ]] || die "wheel metadata version does not match release tag"
  fi
fi

python3 - "$ROOT" <<'PY'
import os, sys
root = os.path.abspath(sys.argv[1])
if os.path.lexists(root) and os.path.islink(root):
    raise SystemExit("LFL_HOME must not be a symlink")
created = not os.path.exists(root)
os.makedirs(root, mode=0o700, exist_ok=True)
st = os.stat(root)
if not os.path.isdir(root) or st.st_uid != os.getuid():
    raise SystemExit("LFL_HOME must be a directory owned by the current user")
os.chmod(root, 0o700)
PY

if [[ -e "$LOCK_DIR" || -L "$LOCK_DIR" ]]; then
  die "another LFL install/rollback/uninstall may be running (lock exists: $LOCK_DIR)"
fi
mkdir -m 700 -- "$LOCK_DIR" || die "could not acquire installer lock"
LOCK_HELD="1"

if [[ "$MODE" == "rollback" ]]; then
  CURRENT_VERSION="$(read_pointer "$ACTIVE_FILE")" || die "no active LFL version is installed"
  TARGET_VERSION="$(read_pointer "$PREVIOUS_FILE")" || die "no previous LFL version is retained; rollback is unavailable"
  [[ "$CURRENT_VERSION" != "$TARGET_VERSION" ]] || die "active and previous versions are identical"
  # The active release may be the broken version we need to escape. Only the
  # rollback target must pass integrity checks before switching the pointer.
  verify_release_dir "$RELEASES/LFL-$TARGET_VERSION" "$TARGET_VERSION"
  assert_no_managed_lfl_processes
  install_launcher
  OLD_PREVIOUS="$TARGET_VERSION"
  POINTER_TRANSACTION_STARTED="1"
  POINTER_PREVIOUS_ATTEMPTED="1"
  write_pointer "$PREVIOUS_FILE" "$CURRENT_VERSION"
  POINTER_ACTIVE_ATTEMPTED="1"
  write_pointer "$ACTIVE_FILE" "$TARGET_VERSION"
  if ! (verify_release_dir "$RELEASES/LFL-$TARGET_VERSION" "$TARGET_VERSION"); then
    write_pointer "$ACTIVE_FILE" "$CURRENT_VERSION"
    write_pointer "$PREVIOUS_FILE" "$TARGET_VERSION"
    POINTER_TRANSACTION_STARTED="0"
    die "rollback validation failed; restored the previous active pointer"
  fi
  POINTER_TRANSACTION_STARTED="0"
  LAUNCHER_CREATED="0"
  LEGACY_BACKUP_CREATED="0"
  printf 'LFL rolled back: %s -> %s\n' "$CURRENT_VERSION" "$TARGET_VERSION"
  exit 0
fi

if [[ -e "$ACTIVE_FILE" || -L "$ACTIVE_FILE" ]]; then
  CURRENT_VERSION="$(read_pointer "$ACTIVE_FILE")"
else
  CURRENT_VERSION=""
fi
if [[ -e "$PREVIOUS_FILE" || -L "$PREVIOUS_FILE" ]]; then
  OLD_PREVIOUS="$(read_pointer "$PREVIOUS_FILE")"
else
  OLD_PREVIOUS=""
fi
if [[ -z "$CURRENT_VERSION" && "$LAUNCHER_KIND" == "managed" ]]; then
  die "managed launcher exists without an active-version pointer; refusing to guess the install state"
fi
if [[ -z "$CURRENT_VERSION" && -n "$OLD_PREVIOUS" ]]; then
  die "inconsistent install state: previous version exists without an active version"
fi
if [[ ( -n "$CURRENT_VERSION" && "$CURRENT_VERSION" != "$RELEASE_VERSION" ) || "$LAUNCHER_KIND" == "legacy-uv" ]]; then
  assert_no_managed_lfl_processes
fi
if [[ -n "$CURRENT_VERSION" ]]; then
  verify_release_dir "$RELEASES/LFL-$CURRENT_VERSION" "$CURRENT_VERSION"
fi

RELEASE_DIR="$RELEASES/LFL-$RELEASE_VERSION"
[[ ! -L "$RELEASES" ]] || die "releases directory must not be a symlink"
if [[ ! -e "$RELEASES" ]]; then
  mkdir -m 700 -- "$RELEASES"
fi
[[ ! -L "$RELEASES" && -d "$RELEASES" ]] || die "unsafe releases directory"
if [[ -d "$RELEASE_DIR" ]]; then
  if [[ -f "$RELEASE_DIR/.installer-incomplete" ]]; then
    [[ "${REUSE_LOCAL_RELEASE:-0}" != "1" ]] || die "retained release is incomplete; use a published release or a verified local wheel"
    [[ "$CURRENT_VERSION" != "$RELEASE_VERSION" && "$OLD_PREVIOUS" != "$RELEASE_VERSION" ]] || die "active/previous release is marked incomplete; refusing cleanup"
    python3 - "$RELEASE_DIR" "$RELEASES" <<'PY'
import os, shutil, sys
target, parent = map(os.path.abspath, sys.argv[1:])
if os.path.dirname(target) != parent or not os.path.basename(target).startswith("LFL-"):
    raise SystemExit("unsafe incomplete release path")
shutil.rmtree(target)
PY
  elif [[ "${REUSE_LOCAL_RELEASE:-0}" != "1" ]]; then
    [[ -f "$RELEASE_DIR/.installer-wheel.sha256" ]] || die "release directory exists without an installer record; refusing overwrite"
    RECORDED_SHA="$(awk 'NR==1 {print $1}' "$RELEASE_DIR/.installer-wheel.sha256")"
    [[ "$RECORDED_SHA" == "$EXPECTED_SHA" ]] || die "version $RELEASE_VERSION is already installed from different bytes; refusing to overwrite it"
    verify_release_dir "$RELEASE_DIR" "$RELEASE_VERSION"
  else
    verify_release_dir "$RELEASE_DIR" "$RELEASE_VERSION"
  fi
fi

if [[ ! -d "$RELEASE_DIR" ]]; then
  [[ -f "${WHEEL_PATH:-}" ]] || die "wheel file is unavailable for new release $RELEASE_VERSION"
  NEW_RELEASE_DIR="$RELEASE_DIR"
  python3 - "$RELEASES" "$RELEASE_DIR" "$RELEASE_VERSION" "$WHEEL_PATH" "$WHEEL_NAME" "$EXPECTED_SHA" "$SOURCE_DESCRIPTION" <<'PY'
import os, shutil, sys
parent, target, version, source, wheel_name, digest, provenance = sys.argv[1:]
parent, target = map(os.path.abspath, (parent, target))
if os.path.dirname(target) != parent or os.path.basename(target) != "LFL-" + version:
    raise SystemExit("unsafe release path")
os.mkdir(target, 0o700)
with open(os.path.join(target, ".installer-incomplete"), "w", encoding="ascii") as f:
    f.write(version + "\n")
os.chmod(os.path.join(target, ".installer-incomplete"), 0o600)
shutil.copyfile(source, os.path.join(target, wheel_name))
with open(os.path.join(target, ".installer-wheel.sha256"), "w", encoding="ascii") as f:
    f.write(f"{digest}  {wheel_name}\n")
with open(os.path.join(target, ".installer-source"), "w", encoding="utf-8") as f:
    f.write(provenance + "\n")
for name in (wheel_name, ".installer-wheel.sha256", ".installer-source"):
    os.chmod(os.path.join(target, name), 0o600)
PY
fi

if [[ -f "$RELEASE_DIR/.installer-incomplete" ]]; then
  UV_BIN="$(bootstrap_uv)"
  [[ -x "$UV_BIN" ]] || die "uv executable not found after bootstrap"
  "$UV_BIN" venv --python 3.13 "$RELEASE_DIR/venv"
  "$UV_BIN" pip install --python "$RELEASE_DIR/venv/bin/python" "$RELEASE_DIR/$WHEEL_NAME"
  "$UV_BIN" pip check --python "$RELEASE_DIR/venv/bin/python"
  verify_release_dir "$RELEASE_DIR" "$RELEASE_VERSION" 1
  python3 - "$RELEASE_DIR/.installer-incomplete" <<'PY'
import os, sys
os.unlink(sys.argv[1])
PY
  NEW_RELEASE_DIR=""
fi

install_launcher
if [[ -n "$CURRENT_VERSION" && "$CURRENT_VERSION" != "$RELEASE_VERSION" ]]; then
  POINTER_TRANSACTION_STARTED="1"
  POINTER_PREVIOUS_ATTEMPTED="1"
  write_pointer "$PREVIOUS_FILE" "$CURRENT_VERSION"
elif [[ -z "$CURRENT_VERSION" ]]; then
  [[ ! -e "$PREVIOUS_FILE" && ! -L "$PREVIOUS_FILE" ]] || die "unexpected previous-version pointer without an active version"
fi
if [[ "$CURRENT_VERSION" != "$RELEASE_VERSION" ]]; then
  POINTER_TRANSACTION_STARTED="1"
  POINTER_ACTIVE_ATTEMPTED="1"
  write_pointer "$ACTIVE_FILE" "$RELEASE_VERSION"
fi

if ! (verify_release_dir "$RELEASE_DIR" "$RELEASE_VERSION"); then
  if [[ -n "$CURRENT_VERSION" ]]; then
    write_pointer "$ACTIVE_FILE" "$CURRENT_VERSION"
  else
    rm -f -- "$ACTIVE_FILE"
  fi
  if [[ -n "$OLD_PREVIOUS" ]]; then
    write_pointer "$PREVIOUS_FILE" "$OLD_PREVIOUS"
  else
    rm -f -- "$PREVIOUS_FILE"
  fi
  POINTER_TRANSACTION_STARTED="0"
  die "post-switch validation failed; the previous active version was restored"
fi
POINTER_TRANSACTION_STARTED="0"

LAUNCHER_CREATED="0"
LEGACY_BACKUP_CREATED="0"
if [[ "$CURRENT_VERSION" == "$RELEASE_VERSION" ]]; then
  printf 'LFL %s is already installed and active; integrity checks passed.\n' "$RELEASE_VERSION"
else
  printf 'LFL %s is installed and active.\n' "$RELEASE_VERSION"
  if [[ -n "$CURRENT_VERSION" ]]; then
    printf 'Previous version %s was retained. Roll back with: bash install_linux.sh --rollback\n' "$CURRENT_VERSION"
  fi
fi
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  printf 'Add this directory to PATH to use lfl from any terminal: %s\n' "$BIN_DIR"
fi
printf 'Next: lfl start (first run configures and live-checks the model), or lfl doctor --online to verify credentials.\n'
