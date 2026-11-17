"""Root-only M0 Oracle UID boundary probe using synthetic files, never a robot.

Run only after the macOS administrator has approved Oracle account provisioning.
All test files are ephemeral. This checks different UNIX UIDs and DAC in both
directions; the separate sandbox-exec probe checks network/device denial.
"""

from __future__ import annotations

import json
import os
import pwd
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path


def _as_user(name: str, path: Path) -> subprocess.CompletedProcess[bytes]:
    actor = pwd.getpwnam(name)

    def drop_privileges() -> None:
        # This probe runs as root only; drop all supplemental groups first.
        # A real process UID change is independently visible to the kernel.
        os.setgroups([actor.pw_gid])
        os.setgid(actor.pw_gid)
        os.setuid(actor.pw_uid)

    child = subprocess.run(
        # /usr/bin/python3 can depend on CLT libraries unreadable by a
        # dedicated low-privilege UID. /bin/cat has no Python/runtime dependency.
        ["/bin/cat", str(path)],
        check=False,
        capture_output=True,
        timeout=12,
        env={"PATH": "/usr/bin:/bin"},
        preexec_fn=drop_privileges,
    )
    if child.returncode not in (0, 1):
        raise RuntimeError(
            f"NO-GO: child as {name} exited {child.returncode}: {child.stderr[:300]!r}"
        )
    return child


def run() -> dict[str, object]:
    if sys.platform != "darwin" or os.geteuid() != 0:
        raise RuntimeError("NO-GO: macOS root-managed verification required")
    oracle, host = pwd.getpwnam("_lfl_oracle"), pwd.getpwnam("yyj")
    if oracle.pw_uid != 463 or oracle.pw_gid != 463 or host.pw_uid == oracle.pw_uid:
        raise RuntimeError("NO-GO: dedicated Oracle identity mismatch")
    if oracle.pw_shell != "/usr/bin/false" or oracle.pw_dir != "/var/empty":
        raise RuntimeError("NO-GO: Oracle login shell or home not locked")

    with tempfile.TemporaryDirectory(prefix="lfl-m0-uid-", dir="/private/var/tmp") as tmp:
        root = Path(tmp)
        root.chmod(0o711)
        files: dict[str, Path] = {}
        canaries: dict[str, bytes] = {}
        for label, actor in (("oracle", oracle), ("host", host)):
            directory = root / label
            directory.mkdir(mode=0o700)
            os.chown(directory, actor.pw_uid, actor.pw_gid)
            path = directory / "synthetic_canary"
            data = secrets.token_bytes(32)
            path.write_bytes(data)
            path.chmod(0o600)
            os.chown(path, actor.pw_uid, actor.pw_gid)
            canaries[label] = data
            files[label] = path

        own_oracle = _as_user("_lfl_oracle", files["oracle"])
        own_host = _as_user("yyj", files["host"])
        cross_host = _as_user("yyj", files["oracle"])
        cross_oracle = _as_user("_lfl_oracle", files["host"])
        def denied(child: subprocess.CompletedProcess[bytes]) -> bool:
            return (
                child.returncode == 1
                and child.stdout == b""
                and (
                    b"Permission denied" in child.stderr
                    or b"Operation not permitted" in child.stderr
                )
            )

        if not (
            own_oracle.returncode == 0
            and own_oracle.stdout == canaries["oracle"]
            and own_host.returncode == 0
            and own_host.stdout == canaries["host"]
            and denied(cross_host)
            and denied(cross_oracle)
        ):
            diagnostic = {
                name: {
                    "exit": child.returncode,
                    "stdout_len": len(child.stdout),
                    "stderr": child.stderr[:180].decode("utf-8", "replace"),
                }
                for name, child in (
                    ("oracle_own", own_oracle),
                    ("host_own", own_host),
                    ("host_cross", cross_host),
                    ("oracle_cross", cross_oracle),
                )
            }
            raise RuntimeError(f"NO-GO: Oracle/Host UID isolation failed: {diagnostic}")

    return {
        "schema": "lfl.embodied.m0-oracle-uid/v1",
        "result": "PASS",
        "oracle_account": "_lfl_oracle",
        "oracle_uid": oracle.pw_uid,
        "oracle_gid": oracle.pw_gid,
        "host_uid": host.pw_uid,
        "distinct_uid": True,
        "oracle_own_read": True,
        "host_own_read": True,
        "host_oracle_read_denied": True,
        "oracle_host_read_denied": True,
        "synthetic_files_cleaned": True,
        "hardware_access": "not_attempted",
        "provider_access": "not_attempted",
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
