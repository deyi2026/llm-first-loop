#!/bin/sh
# Root-only, exact-source, least-privilege UID-463 Oracle installation.
# The only NOPASSWD rule is one exact sandbox-exec + system Python + frozen file.
# Never install generic sudo, a shell command, or a writable project path.
set -eu
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
umask 077

worker_sha=a25e95617869697021609d1fe35b70b6aa07e74ff88866f674074a3f063c5b7b
profile_sha=b3ed2b80cd5ec6201a8a10627461fc82a2c1e7275d505c0cff1a6f34cc869c76
root_dir=/Library/PrivilegedHelperTools/lfl-oracle-v1
sudoers_file=/private/etc/sudoers.d/lfl-oracle-v1
worker_dest=$root_dir/oracle_worker.py
profile_dest=$root_dir/oracle.sb
rule='yyj ALL=(_lfl_oracle) NOPASSWD:NOSETENV: /usr/bin/sandbox-exec -f /Library/PrivilegedHelperTools/lfl-oracle-v1/oracle.sb /usr/bin/python3 -I -S -B /Library/PrivilegedHelperTools/lfl-oracle-v1/oracle_worker.py'

fail() { printf 'ORACLE_HOST_INSTALL=NO_GO reason=%s\n' "$1" >&2; exit 1; }
sha() { /usr/bin/shasum -a 256 "$1" | /usr/bin/awk '{print $1}'; }
check_account() {
    test "$(/usr/bin/id -u _lfl_oracle 2>/dev/null)" = 463 || fail oracle_uid_mismatch
    test "$(/usr/bin/id -g _lfl_oracle 2>/dev/null)" = 463 || fail oracle_gid_mismatch
    /usr/bin/id -Gn _lfl_oracle | /usr/bin/tr ' ' '\n' | /usr/bin/grep -Eq '^(admin|staff|wheel)$' && fail oracle_privileged_group
    test "$(/usr/bin/dscl . -read /Users/_lfl_oracle UserShell | /usr/bin/awk '{print $2}')" = /usr/bin/false || fail oracle_login_shell
    test "$(/usr/bin/dscl . -read /Users/_lfl_oracle NFSHomeDirectory | /usr/bin/awk '{print $2}')" = /var/empty || fail oracle_home
}
check_installed() {
    test -d "$root_dir" && test ! -L "$root_dir" || fail no_trusted_root_dir
    test "$(/usr/bin/stat -f %u "$root_dir")" = 0 || fail untrusted_root_dir_owner
    test "$(/usr/bin/stat -f %Lp "$root_dir")" = 755 || fail root_dir_mode_not_0755
    test -f "$worker_dest" && test ! -L "$worker_dest" || fail no_fixed_worker
    test -f "$profile_dest" && test ! -L "$profile_dest" || fail no_fixed_profile
    test "$(/usr/bin/stat -f %u "$worker_dest")" = 0 || fail worker_not_root_owned
    test "$(/usr/bin/stat -f %u "$profile_dest")" = 0 || fail profile_not_root_owned
    test "$(/usr/bin/stat -f %Lp "$worker_dest")" = 555 || fail worker_mode_not_0555
    test "$(/usr/bin/stat -f %Lp "$profile_dest")" = 444 || fail profile_mode_not_0444
    test "$(sha "$worker_dest")" = "$worker_sha" || fail worker_digest_mismatch
    test "$(sha "$profile_dest")" = "$profile_sha" || fail profile_digest_mismatch
    test -f "$sudoers_file" && test ! -L "$sudoers_file" || fail no_exact_sudoers_rule
    test "$(/usr/bin/stat -f %u "$sudoers_file")" = 0 || fail sudoers_not_root_owned
    test "$(/usr/bin/stat -f %Lp "$sudoers_file")" = 440 || fail sudoers_mode_not_0440
    test "$(/usr/bin/cat "$sudoers_file")" = "$rule" || fail sudoers_rule_mismatch
    /usr/sbin/visudo -cf "$sudoers_file" >/dev/null || fail sudoers_syntax_invalid
    printf 'ORACLE_HOST_INSTALL=PASS uid=463 exact_command=true root_owned=true sha256=%s\n' "$worker_sha"
}

test "$(/usr/bin/uname -s)" = Darwin || fail macos_required
check_account
case "${1:-}" in
    --check)
        check_installed
        exit 0
        ;;
    --revoke)
        test "$(/usr/bin/id -u)" = 0 || fail root_required
        if test -e "$sudoers_file" || test -L "$sudoers_file"; then
            test -f "$sudoers_file" && test ! -L "$sudoers_file" || fail unsafe_sudoers_file
            test "$(/usr/bin/cat "$sudoers_file")" = "$rule" || fail refuse_remove_modified_sudoers
            /bin/rm -- "$sudoers_file"
        fi
        printf 'ORACLE_HOST_INSTALL=REVOKED sudoers_rule_removed=true\n'
        exit 0
        ;;
    --apply) ;;
    *) fail usage_check_apply_revoke ;;
esac

test "$(/usr/bin/id -u)" = 0 || fail root_required
source_dir=$(CDPATH='' /bin/pwd -P)
# The caller must execute this script from its root-owned staging directory.
test "$(/usr/bin/stat -f %u "$source_dir")" = 0 || fail staging_not_root_owned
test "$(/usr/bin/stat -f %u "$0")" = 0 || fail installer_not_root_owned
worker_src=$source_dir/m1_host_oracle_worker_macos.py
profile_src=$source_dir/m1_host_oracle_macos.sb
for path in "$worker_src" "$profile_src"; do
    test -f "$path" && test ! -L "$path" || fail missing_or_symlink_source
    test "$(/usr/bin/stat -f %u "$path")" = 0 || fail source_not_root_owned
done
test "$(sha "$worker_src")" = "$worker_sha" || fail worker_source_sha_mismatch
test "$(sha "$profile_src")" = "$profile_sha" || fail profile_source_sha_mismatch
test "$(/usr/bin/stat -f %u /Library/PrivilegedHelperTools)" = 0 || fail helper_parent_not_root_owned

if test -e "$root_dir" || test -L "$root_dir"; then
    test -d "$root_dir" && test ! -L "$root_dir" || fail unsafe_existing_directory
    test "$(/usr/bin/stat -f %u "$root_dir")" = 0 || fail existing_dir_not_root_owned
fi
for path in "$worker_dest" "$profile_dest"; do
    if test -e "$path" || test -L "$path"; then
        test -f "$path" && test ! -L "$path" || fail unsafe_existing_target
    fi
done
if test -e "$worker_dest" || test -L "$worker_dest"; then
    test "$(sha "$worker_dest")" = "$worker_sha" || fail existing_worker_conflict
fi
if test -e "$profile_dest" || test -L "$profile_dest"; then
    test "$(sha "$profile_dest")" = "$profile_sha" || fail existing_profile_conflict
fi
if test -e "$sudoers_file" || test -L "$sudoers_file"; then
    test -f "$sudoers_file" && test ! -L "$sudoers_file" || fail unsafe_existing_sudoers
    test "$(/usr/bin/cat "$sudoers_file")" = "$rule" || fail existing_sudoers_conflict
fi

/usr/bin/install -d -o root -g wheel -m 0755 "$root_dir"
/usr/bin/install -o root -g wheel -m 0555 "$worker_src" "$worker_dest"
/usr/bin/install -o root -g wheel -m 0444 "$profile_src" "$profile_dest"
test "$(sha "$worker_dest")" = "$worker_sha" || fail installed_worker_sha_mismatch
test "$(sha "$profile_dest")" = "$profile_sha" || fail installed_profile_sha_mismatch

# Root preflight (no persistent sudo rule yet): prove the fixed Worker really
# starts as UID463 with the exact sandbox and Apple system Python. Fail closed
# if this host's Xcode Python runtime is unreadable to the isolated identity.
preflight_payload='{"snapshot":{"cube":{"pos":[0.1,0.0,0.06],"vel":[0.0,0.0,0.0]},"weld_active":true,"contact_pairs":[["cube_geom","fingertip_left",-0.001]]},"claim_kind":"grasp","scene_epoch":3,"experiment_id":"M1-UID463-ROOT-PREFLIGHT"}'
preflight=$(/usr/bin/printf '%s' "$preflight_payload" | /usr/bin/sudo -n -u _lfl_oracle \
    /usr/bin/sandbox-exec -f "$profile_dest" /usr/bin/python3 -I -S -B "$worker_dest") || fail uid463_worker_preflight_failed
case "$preflight" in
    *'"oracle_uid": 463'*'"verdict": "success"'*) ;;
    *) fail uid463_worker_preflight_wrong_receipt ;;
esac

tmp_rule=$(/usr/bin/mktemp /private/var/tmp/lfl-oracle-sudoers.XXXXXXXX)
new_rule=0
success=0
cleanup() {
    if test "$new_rule" = 1 && test "$success" != 1; then
        /bin/rm -f "$sudoers_file"
    fi
    /bin/rm -f "$tmp_rule"
}
trap cleanup EXIT HUP INT TERM
/usr/bin/printf '%s\n' "$rule" > "$tmp_rule"
/usr/sbin/visudo -cf "$tmp_rule" >/dev/null || fail sudoers_preflight_failed
if test ! -e "$sudoers_file"; then
    /usr/bin/install -o root -g wheel -m 0440 "$tmp_rule" "$sudoers_file"
    new_rule=1
fi
check_installed
success=1
