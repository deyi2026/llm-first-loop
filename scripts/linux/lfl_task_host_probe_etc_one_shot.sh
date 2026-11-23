#!/usr/bin/env bash
# Deepin25 /etc Polkit rules.d canary. Never modifies immutable /usr.
# Must be started by the Owner in a local active seat0 graphical Terminal.
# Does not issue a Task Lease, change LFL services, or authorize general Shell.
set -Eeuo pipefail
umask 077
MODE="${1:---check}"
case "$MODE" in --check|--run|--run-console|--cleanup) ;; *) echo 'Usage: script --check|--run|--run-console|--cleanup' >&2; exit 64;; esac
BASE="$(cd -- "$(dirname -- "$0")" && pwd -P)"
HELPER_SRC="$BASE/lfl_task_host_probe.py"
RULE_SRC="$BASE/../../packaging/linux/00-lfl-task-host-probe.rules"
[[ -f "$RULE_SRC" ]] || RULE_SRC="$BASE/00-lfl-task-host-probe.rules"
HELPER_SHA='072ffb05fa7dad2500310fad95f876b3fc504e631211ddfa563d8ba4e0fd1d11'
RULE_SHA='86199e2884246274bdd7d1b44591736c1761df088b9f140fdc4465d9fdd3d630'
HELPER_DST='/usr/local/libexec/lfl-task-host-probe'
RULE_DST='/etc/polkit-1/rules.d/00-lfl-task-host-probe.rules'
LEGACY_POLICY_DST='/usr/share/polkit-1/actions/org.llmfirstloop.task-host-probe.policy'
RECEIPT_DIR='/var/lib/lfl-task-host-probe/receipts'
STATE_DIR="$HOME/.local/state/lfl-task-t2-polkit-etc-20261123"
RESULT="$STATE_DIR/one-shot-polkit-etc-result.txt"

[[ "$(id -u)" -ne 0 ]] || { echo 'DENY: run as ordinary desktop user, not root'; exit 77; }
[[ "$(sha256sum "$HELPER_SRC" | cut -d' ' -f1)" == "$HELPER_SHA" ]] || {
  echo 'DENY: helper content changed'; exit 77;
}
[[ "$(sha256sum "$RULE_SRC" | cut -d' ' -f1)" == "$RULE_SHA" ]] || {
  echo 'DENY: scoped /etc rule content changed'; exit 77;
}
for command in pkexec pkaction sudo timeout sha256sum loginctl findmnt; do
  command -v "$command" >/dev/null || { echo "HOLD: missing $command"; exit 78; }
done
pkaction --action-id org.freedesktop.policykit.exec >/dev/null
[[ ",$(findmnt -T /etc/polkit-1/rules.d -no OPTIONS)," == *,rw,* ]] || {
  echo 'HOLD: /etc rules directory is not writable'; exit 78;
}
[[ ",$(findmnt -T /usr/local/libexec -no OPTIONS)," == *,rw,* ]] || {
  echo 'HOLD: /usr/local/libexec is not writable'; exit 78;
}
[[ "$(stat -c '%U %a' /usr/local/libexec)" == 'root 755' ]] || {
  echo 'HOLD: helper parent ownership or mode unexpected'; exit 78;
}
[[ "$(stat -c '%U %a' /etc/polkit-1/rules.d)" == 'root 750' ]] || {
  echo 'HOLD: rule parent ownership or mode unexpected'; exit 78;
}
# Deepin25 DDE may set XDG_SESSION_ID=14615 in an app.slice GUI Terminal
# even though the *process* has no kernel logind session. Polkit evaluates the
# process, not the spoofable environment. Never infer local authorization from
# loginctl show-session "$XDG_SESSION_ID" alone.
require_kernel_bound_local_session() {
  local kind="$1" session_info
  [[ -n "${XDG_SESSION_ID:-}" ]] || {
    echo 'HOLD: no caller logind session; use a physical local console'; exit 78;
  }
  session_info="$(loginctl show-session self -p Id -p Seat -p Remote -p Active -p Type 2>/dev/null)" || {
    echo 'HOLD: caller is not kernel-bound to a logind session; DDE app.slice GUI Terminal cannot satisfy Polkit local/active. Use --run-console on physical tty3'; exit 78;
  }
  for required in "Id=$XDG_SESSION_ID" 'Seat=seat0' 'Remote=no' 'Active=yes'; do
    if ! printf '%s\n' "$session_info" | grep -Fxq -- "$required"; then
      echo 'HOLD: caller session identity, seat, remote or active state does not match kernel logind'; exit 78;
    fi
  done
  if [[ "$kind" == gui ]]; then
    [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] || {
      echo 'HOLD: no local graphical display'; exit 78;
    }
    if ! printf '%s\n' "$session_info" | grep -Eq '^Type=(x11|wayland)$'; then
      echo 'HOLD: caller is not in a kernel-bound graphical session'; exit 78;
    fi
  else
    [[ -t 0 && -t 1 && -z "${SSH_CONNECTION:-}${SSH_TTY:-}" ]] || {
      echo 'HOLD: console authorization requires an interactive physical TTY, not SSH'; exit 78;
    }
    if ! printf '%s\n' "$session_info" | grep -Fxq 'Type=tty'; then
      echo 'HOLD: caller is not in a kernel-bound local TTY session'; exit 78;
    fi
  fi
}
if [[ "$MODE" == --cleanup ]]; then
  if [[ ! -e "$HELPER_DST" && ! -L "$HELPER_DST" &&
        ! -e "$RULE_DST" && ! -L "$RULE_DST" ]]; then
    echo 'DEEPIN_ETC_POLKIT_ALREADY_CLEAN'; exit 0
  fi
  if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    require_kernel_bound_local_session gui
  else
    require_kernel_bound_local_session console
  fi
  echo 'Recovery requires local administrator approval; never removes unknown content.'
  sudo -v
  for entry in "$RULE_DST:$RULE_SHA" "$HELPER_DST:$HELPER_SHA"; do
    target="${entry%%:*}"; expected="${entry##*:}"
    if [[ -e "$target" || -L "$target" ]]; then
      [[ "$(sudo sha256sum "$target" | cut -d' ' -f1)" == "$expected" ]] || {
        echo "HOLD: unexpected content at $target, refusing removal"; exit 79;
      }
      sudo rm -f -- "$target"
    fi
  done
  [[ ! -e "$HELPER_DST" && ! -L "$HELPER_DST" &&
     ! -e "$RULE_DST" && ! -L "$RULE_DST" ]] || exit 79
  echo 'DEEPIN_ETC_POLKIT_EXACT_CLEANUP_PASS'; exit 0
fi
for target in "$HELPER_DST" "$RULE_DST" "$LEGACY_POLICY_DST"; do
  [[ ! -e "$target" && ! -L "$target" ]] || {
    echo "HOLD: fixed target already exists: $target"; exit 78;
  }
done
echo 'DEEPIN_ETC_POLKIT_PREFLIGHT_PASS: exact hashes, no existing targets, /etc and /usr/local writable, no /usr change'
if [[ "$MODE" == --check ]]; then
  echo 'CHECK_ONLY: no sudo, no pkexec, no install, no restart; caller kernel logind session is verified only in --run or --run-console'
  exit 0
fi
if [[ "$MODE" == --run ]]; then
  require_kernel_bound_local_session gui
else
  require_kernel_bound_local_session console
fi
# User must authorize the two bounded system writes via the local sudo prompt.
echo 'Owner local admin authentication required; do not enter passwords in chat.'
sudo -v
mkdir -p -m 0700 "$STATE_DIR"
chmod 0700 "$STATE_DIR"
printf 'state=started\npolicy=etc_scoped_builtin_pkexec\nsigned_task_lease=false\n' > "$RESULT"
chmod 0600 "$RESULT"
installed_helper=0
installed_rule=0
cleanup() {
  local rc=$?
  trap - EXIT
  if (( installed_rule )); then
    if [[ "$(sudo sha256sum "$RULE_DST" 2>/dev/null | cut -d' ' -f1)" == "$RULE_SHA" ]]; then
      sudo rm -f -- "$RULE_DST" || rc=79
    else
      echo 'HOLD: rule changed; refusing unsafe cleanup' >&2
      rc=79
    fi
  fi
  if (( installed_helper )); then
    if [[ "$(sudo sha256sum "$HELPER_DST" 2>/dev/null | cut -d' ' -f1)" == "$HELPER_SHA" ]]; then
      sudo rm -f -- "$HELPER_DST" || rc=79
    else
      echo 'HOLD: helper changed; refusing unsafe cleanup' >&2
      rc=79
    fi
  fi
  if [[ -e "$RULE_DST" || -L "$RULE_DST" || -e "$HELPER_DST" || -L "$HELPER_DST" ]]; then
    echo 'HOLD: fixed helper or /etc rule remains; manual rollback required' >&2
    rc=79
  else
    echo 'DEEPIN_ETC_POLKIT_TEMP_HELPER_RULE_REMOVED'
  fi
  printf 'exit_code=%s\nhelper_absent=%s\nrule_absent=%s\n' \
    "$rc" "$(test ! -e "$HELPER_DST" && echo yes || echo no)" \
    "$(test ! -e "$RULE_DST" && echo yes || echo no)" >> "$RESULT"
  chmod 0600 "$RESULT"
  exit "$rc"
}
trap cleanup EXIT
sudo install -d -o root -g root -m 0700 /var/lib/lfl-task-host-probe "$RECEIPT_DIR"
installed_helper=1
sudo install -o root -g root -m 0555 -T "$HELPER_SRC" "$HELPER_DST"
[[ "$(sudo stat -c '%U:%G %a' "$HELPER_DST")" == 'root:root 555' ]] || exit 78
[[ "$(sudo sha256sum "$HELPER_DST" | cut -d' ' -f1)" == "$HELPER_SHA" ]] || exit 78
installed_rule=1
sudo install -o root -g root -m 0644 -T "$RULE_SRC" "$RULE_DST"
[[ "$(sudo stat -c '%U:%G %a' "$RULE_DST")" == 'root:root 644' ]] || exit 78
[[ "$(sudo sha256sum "$RULE_DST" | cut -d' ' -f1)" == "$RULE_SHA" ]] || exit 78
[[ ! -e "$LEGACY_POLICY_DST" ]] || exit 78
# Polkit automatically reloads /etc rules. No daemon or OS restart.
sleep 2
challenge="$(/usr/bin/python3 -I -c 'import secrets;print(secrets.token_hex(16))')"
if [[ "$MODE" == --run-console ]]; then
  echo 'POLKIT_ETC_LOCAL_TTY_ADMIN_AUTH_EXPECTED (builtin pkexec scoped by /etc rule; terminal authentication agent)'
  response="$(timeout 180 pkexec "$HELPER_DST" attest "$challenge")"
else
  echo 'POLKIT_ETC_GUI_ADMIN_AUTH_EXPECTED (builtin pkexec scoped by /etc rule)'
  response="$(timeout 180 pkexec --disable-internal-agent "$HELPER_DST" attest "$challenge")"
fi
printf '%s\n' "$response" | /usr/bin/python3 -I -c '
import json,sys
x=json.load(sys.stdin)
assert x["result"]=="POLKIT_ROOT_RECEIPT_WRITTEN"
assert x["signed_task_lease"] is False
assert len(x["challenge"])==32
print("DEEPIN_ETC_POLKIT_GUI_ROOT_RECEIPT_PASS",x["receipt_sha256"])
'
receipt="$RECEIPT_DIR/$challenge.json"
[[ "$(sudo stat -c '%U:%G %a' "$receipt")" == 'root:root 600' ]] || exit 78
receipt_sha="$(sudo sha256sum "$receipt" | cut -d' ' -f1)"
[[ "$receipt_sha" == "$(printf '%s\n' "$response" | /usr/bin/python3 -I -c 'import json,sys;print(json.load(sys.stdin)["receipt_sha256"])')" ]] || exit 78
set +e
sudo env "PKEXEC_UID=$(id -u)" "$HELPER_DST" attest "$challenge" >/dev/null 2>&1
replay_rc=$?
/usr/bin/python3 -I "$HELPER_DST" attest "$(/usr/bin/python3 -I -c 'import secrets;print(secrets.token_hex(16))')" >/dev/null 2>&1
unprivileged_rc=$?
set -e
[[ "$replay_rc" == 78 && "$unprivileged_rc" == 77 ]] || {
  echo "HOLD: replay=$replay_rc or unprivileged=$unprivileged_rc not DENY"; exit 78;
}
printf 'state=physical_local_pass\nreceipt_sha256=%s\nreplay=deny\nunprivileged=deny\nremote_ssh=not_yet_verified\n' "$receipt_sha" >> "$RESULT"
echo "DEEPIN_ETC_POLKIT_LOCAL_PHYSICAL_PASS receipt_sha=$receipt_sha replay=DENY unprivileged=DENY remote_ssh=NOT_VERIFIED"
echo 'ONE_SHOT_COMPLETE: fixed helper and /etc rule are removed on EXIT; no service or OS restart.'
