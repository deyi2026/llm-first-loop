#!/usr/bin/env bash
# Remove LFL application binaries while preserving configuration and user data.
set -Eeuo pipefail
umask 077

usage() {
  cat <<'EOF'
LFL Linux uninstaller

Usage:
  bash uninstall_linux.sh
  bash uninstall_linux.sh --yes

The uninstaller removes managed LFL release environments and the managed launcher.
It preserves LFL_HOME, including .env, data, methods, experiences, and the uv bootstrap.
It never uses sudo and never deletes user data.

Options:
  --yes       Skip the interactive confirmation.
  -h, --help  Show this help.
EOF
}

die() { printf 'LFL uninstaller: %s\n' "$*" >&2; exit 1; }
YES="0"
while (($#)); do
  case "$1" in
    --yes) YES="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (use --help)" ;;
  esac
done

[[ "$(uname -s)" == "Linux" ]] || die "Linux only"
[[ "$(id -u)" != "0" ]] || die "run as a normal user, not root; sudo is not required"
[[ -n "${HOME:-}" && "$HOME" == /* && -d "$HOME" ]] || die "HOME must be an existing absolute directory"
command -v python3 >/dev/null 2>&1 || die "python3 is required"

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
LAUNCHER="$HOME/.local/bin/lfl"
LOCK_DIR="$ROOT/.linux-install.lock"
LEGACY_LAUNCHER="$ROOT/.linux-legacy-lfl-launcher"

[[ -d "$ROOT" && ! -L "$ROOT" ]] || die "no managed LFL_HOME found at $ROOT"
[[ "$(stat -c '%u' "$ROOT")" == "$(id -u)" ]] || die "LFL_HOME must be owned by the current user"
[[ -f "$LAUNCHER" && ! -L "$LAUNCHER" ]] || die "managed LFL launcher not found at $LAUNCHER"
grep -Fqx '# LFL_LINUX_LAUNCHER_V1' "$LAUNCHER" || die "refusing to remove an unmanaged launcher"
grep -Fqx "# LFL_LINUX_INSTALL_ROOT: $ROOT" "$LAUNCHER" || die "launcher belongs to a different LFL_HOME"

if [[ -e "$LOCK_DIR" || -L "$LOCK_DIR" ]]; then
  die "another LFL install/rollback/uninstall may be running (lock exists)"
fi
mkdir -m 700 -- "$LOCK_DIR" || die "could not acquire uninstall lock"
LOCK_HELD="1"
cleanup() { if [[ "$LOCK_HELD" == "1" ]]; then rmdir "$LOCK_DIR" 2>/dev/null || true; fi; }
trap cleanup EXIT

if [[ "$YES" != "1" ]]; then
  [[ -t 0 ]] || die "non-interactive uninstall requires --yes"
  printf 'Remove LFL application versions and launcher? Configuration and user data will be kept. Type yes: '
  IFS= read -r answer
  [[ "$answer" == "yes" ]] || die "cancelled; no files were changed"
fi

command -v ps >/dev/null 2>&1 || die "cannot verify running LFL processes because ps is unavailable; no files were changed"
process_list="$(ps -eo pid=,args=)" || die "cannot verify running LFL processes; no files were changed"
while IFS= read -r line; do
  [[ -n "$line" ]] || continue
  pid="${line#"${line%%[![:space:]]*}"}"
  pid="${pid%%[[:space:]]*}"
  [[ "$pid" =~ ^[0-9]+$ ]] || continue
  [[ "$pid" != "$$" && "$pid" != "$PPID" ]] || continue
  case "$line" in
    *"$ROOT/releases/LFL-"*"/venv/bin/"*|*"/uv/tools/llm-first-loop/"*)
      die "an LFL process is still running (pid $pid); stop it before uninstalling"
      ;;
  esac
done <<< "$process_list"

python3 - "$ROOT" "$LAUNCHER" "$LEGACY_LAUNCHER" <<'PY'
import os, re, shutil, sys
root, launcher, legacy = map(os.path.abspath, sys.argv[1:])
releases = os.path.join(root, "releases")
active = os.path.join(root, ".LFL-active-version")
previous = os.path.join(root, ".LFL-previous-version")
if os.path.islink(releases):
    raise SystemExit("refusing symlinked releases directory")
release_dirs = []
if os.path.exists(releases):
    if not os.path.isdir(releases):
        raise SystemExit("releases path is not a directory")
    for name in os.listdir(releases):
        path = os.path.join(releases, name)
        if not re.fullmatch(r"LFL-[0-9]+\.[0-9]+\.[0-9]+", name) or os.path.islink(path) or not os.path.isdir(path):
            raise SystemExit(f"unexpected entry in releases directory; nothing was removed: {name}")
        if not (os.path.isfile(os.path.join(path, ".installer-wheel.sha256")) or os.path.isfile(os.path.join(path, ".installer-incomplete"))):
            raise SystemExit(f"unrecognized release directory; nothing was removed: {name}")
        release_dirs.append(path)
for path in (active, previous):
    if os.path.islink(path):
        raise SystemExit(f"refusing symlinked version pointer: {os.path.basename(path)}")
    if os.path.exists(path):
        if not os.path.isfile(path):
            raise SystemExit(f"unsafe version pointer: {os.path.basename(path)}")
        value = open(path, encoding="ascii").read().strip()
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
            raise SystemExit(f"invalid version pointer: {os.path.basename(path)}")
if os.path.lexists(legacy):
    if not os.path.islink(legacy):
        raise SystemExit("legacy launcher backup is not a symlink; refusing removal")
    target = os.path.realpath(legacy)
    if "/uv/tools/llm-first-loop/" not in target or not os.path.exists(target):
        raise SystemExit("legacy uv launcher target is unavailable; refusing removal")

# All entries are validated before deleting any release. User data and config are untouched.
for path in release_dirs:
    if os.path.dirname(path) != releases:
        raise SystemExit("release path escaped its parent")
    shutil.rmtree(path)
if os.path.isdir(releases) and not os.listdir(releases):
    os.rmdir(releases)
for path in (active, previous):
    if os.path.exists(path):
        os.unlink(path)
if os.path.lexists(legacy):
    os.replace(legacy, launcher)
elif os.path.exists(launcher):
    os.unlink(launcher)
print("Removed managed LFL application versions; kept .env, data, methods, experiences, and other user files.")
PY
