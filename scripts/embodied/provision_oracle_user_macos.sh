#!/bin/sh
# One-shot, idempotent macOS M0 Oracle service identity provisioning.
# Run --check without privilege; --apply ONLY via a macOS administrator-approved
# managed host action. Never ask an LLM/chat for an administrator password.
set -eu

name=_lfl_oracle
uid=463
gid=463
user_path=/Users/$name
group_path=/Groups/$name

die() { printf 'NO-GO: %s\n' "$1" >&2; exit 1; }
user_exists() { /usr/bin/dscl . -read "$user_path" >/dev/null 2>&1; }
group_exists() { /usr/bin/dscl . -read "$group_path" >/dev/null 2>&1; }

verify() {
    test "$(/usr/bin/id -u "$name" 2>/dev/null)" = "$uid" || die 'oracle UID mismatch'
    test "$(/usr/bin/id -g "$name" 2>/dev/null)" = "$gid" || die 'oracle GID mismatch'
    test "$(/usr/bin/dscl . -read "$user_path" UserShell | /usr/bin/awk '{print $2}')" = /usr/bin/false || die 'oracle login shell enabled'
    test "$(/usr/bin/dscl . -read "$user_path" NFSHomeDirectory | /usr/bin/awk '{print $2}')" = /var/empty || die 'oracle home mismatch'
    /usr/bin/dscl . -read "$user_path" AuthenticationAuthority | /usr/bin/grep -Fq 'DisabledUser' || die 'oracle authentication not disabled'
    /usr/bin/id -Gn "$name" | /usr/bin/tr ' ' '\n' | /usr/bin/grep -Eq '^(admin|staff|wheel)$' && die 'oracle has privileged/shared group'
    /usr/bin/dscl . -read "$group_path" PrimaryGroupID | /usr/bin/grep -Eq "^PrimaryGroupID: $gid$" || die 'oracle group mismatch'
    printf 'ORACLE_ACCOUNT_VERIFIED name=%s uid=%s gid=%s shell=/usr/bin/false home=/var/empty auth=disabled admin_group=false\n' "$name" "$uid" "$gid"
}

test "$(/usr/bin/uname -s)" = Darwin || die 'macOS host required'
case "${1:-}" in
    --check)
        if user_exists && group_exists; then
            verify
        elif user_exists || group_exists; then
            die 'partial existing Oracle identity; manual reconciliation required'
        else
            printf 'ORACLE_ACCOUNT_ABSENT name=%s uid=%s gid=%s\n' "$name" "$uid" "$gid"
        fi
        exit 0
        ;;
    --apply) ;;
    *) die 'usage: provision_oracle_user_macos.sh --check|--apply' ;;
esac

test "$(/usr/bin/id -u)" = 0 || die 'root required; use macOS administrator-approved host action'
if user_exists && group_exists; then
    verify
    exit 0
fi
if user_exists || group_exists; then
    die 'partial existing Oracle identity; manual reconciliation required'
fi

# Collision checks must run under the privileged actor immediately before write.
if /usr/bin/dscl . -list /Users UniqueID | /usr/bin/awk -v n="$uid" '$2 == n {found=1} END {exit !found}'; then
    die 'UID already allocated'
fi
if /usr/bin/dscl . -list /Groups PrimaryGroupID | /usr/bin/awk -v n="$gid" '$2 == n {found=1} END {exit !found}'; then
    die 'GID already allocated'
fi

committed=0
rollback() {
    if test "$committed" = 0; then
        /usr/bin/dscl . -delete "$user_path" >/dev/null 2>&1 || true
        /usr/bin/dscl . -delete "$group_path" >/dev/null 2>&1 || true
    fi
}
trap rollback EXIT

/usr/bin/dscl . -create "$group_path"
/usr/bin/dscl . -create "$group_path" PrimaryGroupID "$gid"
/usr/bin/dscl . -create "$group_path" RealName 'LFL M0 Oracle Isolated Group'
/usr/bin/dscl . -create "$group_path" Password '*'

/usr/bin/dscl . -create "$user_path"
/usr/bin/dscl . -create "$user_path" UniqueID "$uid"
/usr/bin/dscl . -create "$user_path" PrimaryGroupID "$gid"
/usr/bin/dscl . -create "$user_path" RealName 'LFL M0 Oracle Isolated Service'
/usr/bin/dscl . -create "$user_path" UserShell /usr/bin/false
/usr/bin/dscl . -create "$user_path" NFSHomeDirectory /var/empty
/usr/bin/dscl . -create "$user_path" IsHidden 1
/usr/bin/dscl . -create "$user_path" AuthenticationAuthority ';DisabledUser;'
/usr/bin/dscl . -create "$user_path" Password '*'

verify
committed=1
trap - EXIT
printf 'ORACLE_ACCOUNT_CREATED name=%s uid=%s gid=%s\n' "$name" "$uid" "$gid"
