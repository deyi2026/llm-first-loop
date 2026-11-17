"""Root-only M0 Oracle UID boundary probe using synthetic files, never a robot.

Run only after the macOS administrator has approved Oracle account provisioning.
All test files are ephemeral. This checks different UNIX UIDs and DAC in both
directions; the separate sandbox-exec probe checks network/device denial.
"""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

_READ = r"""
import hashlib
import os
import sys
try:
    data = open(sys.argv[1], 'rb').read()
except PermissionError:
    print('DENIED')
else:
    print('READ:' + hashlib.sha256(data).hexdigest())
"""


def _as_user(name: str, path: Path) -> str:
    child = subprocess.run(
        ["/usr/bin/sudo", "-n", "-u", name, "/usr/bin/python3", "-c", _READ, str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=12,
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if child.returncode != 0:
        raise RuntimeError(f"NO-GO: child as {name} exited {child.returncode}")
    return child.stdout.strip()


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
        digests: dict[str, str] = {}
        for label, actor in (("oracle", oracle), ("host", host)):
            directory = root / label
            directory.mkdir(mode=0o700)
            os.chown(directory, actor.pw_uid, actor.pw_gid)
            path = directory / "synthetic_canary"
            data = secrets.token_bytes(32)
            path.write_bytes(data)
            path.chmod(0o600)
            os.chown(path, actor.pw_uid, actor.pw_gid)
            digests[label] = hashlib.sha256(data).hexdigest()
            files[label] = path

        own_oracle = _as_user("_lfl_oracle", files["oracle"])
        own_host = _as_user("yyj", files["host"])
        cross_host = _as_user("yyj", files["oracle"])
        cross_oracle = _as_user("_lfl_oracle", files["host"])
        if not (
            own_oracle == "READ:" + digests["oracle"]
            and own_host == "READ:" + digests["host"]
            and cross_host == "DENIED"
            and cross_oracle == "DENIED"
        ):
            raise RuntimeError("NO-GO: Oracle/Host UID isolation proof failed")

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
