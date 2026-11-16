"""B1-1: premerge_gate.py --mode ci 合同测试（冻结 DESIGN-20261116 v1.9）。

黑盒 subprocess 调用：脚本只读、无网络、无 Git 写副作用，输入全部来自 CLI
（冻结/可信 run 事件数据），输出为机器可消费 JSON 回执。四个 push/PR 兄弟
job 集合与 .github/workflows/ci.yml 一致：security-scan / test /
linux-installer / ambient-env-gate。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "premerge_gate.py"

RUN_ID = 424242
SHA_HEAD = "1111111111111111111111111111111111111111"
SHA_BASE = "2222222222222222222222222222222222222222"
SHA_MERGE = "3333333333333333333333333333333333333333"

SIBLINGS = ("security-scan", "test", "linux-installer", "ambient-env-gate")


def _run_gate(*extra: str) -> tuple[int, dict[str, Any], str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "ci", *extra],
        capture_output=True,
        text=True,
        check=False,
    )
    receipt: dict[str, Any] = {}
    if proc.stdout.strip():
        receipt = json.loads(proc.stdout)
    return proc.returncode, receipt, proc.stderr


def _needs_json(**overrides: dict[str, Any]) -> str:
    needs: dict[str, dict[str, Any]] = {job: {"result": "success", "run_id": RUN_ID} for job in SIBLINGS}
    for job, entry in overrides.items():
        needs[job] = entry
    return json.dumps(needs)


def _push_args(needs: str) -> list[str]:
    return [
        "--event",
        "push",
        "--run-id",
        str(RUN_ID),
        "--head-sha",
        SHA_HEAD,
        "--needs-json",
        needs,
    ]


def _pr_args(
    needs: str,
    *,
    head: str | None = SHA_HEAD,
    base: str | None = SHA_BASE,
    merge: str | None = SHA_MERGE,
) -> list[str]:
    args = ["--event", "pull_request", "--run-id", str(RUN_ID), "--needs-json", needs]
    if head is not None:
        args += ["--pr-head-sha", head]
    if base is not None:
        args += ["--pr-base-sha", base]
    if merge is not None:
        args += ["--pr-merge-sha", merge]
    return args


def test_push_success_passes_with_default_required_set() -> None:
    rc, receipt, _ = _run_gate(*_push_args(_needs_json()))
    assert rc == 0, receipt
    assert receipt["verdict"] == "pass"
    assert receipt["event"] == "push"
    assert receipt["run_id"] == RUN_ID
    assert receipt["required_jobs"] == list(SIBLINGS)
    assert receipt["same_run"] is True
    assert receipt["all_success"] is True
    assert receipt["read_only"] is True
    assert receipt["branch_protection"]["host_verified"] is False


def test_pull_request_success_with_implicit_same_run_passes() -> None:
    needs = json.dumps({job: {"result": "success"} for job in SIBLINGS})
    rc, receipt, _ = _run_gate(*_pr_args(needs))
    assert rc == 0, receipt
    assert receipt["verdict"] == "pass"
    assert receipt["identity"]["pr_head_sha"] == SHA_HEAD
    assert receipt["identity"]["pr_base_sha"] == SHA_BASE
    assert receipt["identity"]["pr_merge_sha"] == SHA_MERGE
    assert receipt["same_run"] is True


def test_missing_sibling_fails() -> None:
    needs = json.dumps({job: {"result": "success", "run_id": RUN_ID} for job in SIBLINGS[:3]})
    rc, receipt, _ = _run_gate(*_push_args(needs))
    assert rc != 0
    assert receipt["verdict"] == "fail"
    assert "missing_need:ambient-env-gate" in receipt["reasons"]


def test_skipped_sibling_fails() -> None:
    needs = _needs_json(**{"ambient-env-gate": {"result": "skipped", "run_id": RUN_ID}})
    rc, receipt, _ = _run_gate(*_push_args(needs))
    assert rc != 0
    assert receipt["verdict"] == "fail"
    assert "need_not_success:ambient-env-gate:skipped" in receipt["reasons"]


def test_failed_sibling_fails() -> None:
    needs = _needs_json(**{"test": {"result": "failure", "run_id": RUN_ID}})
    rc, receipt, _ = _run_gate(*_push_args(needs))
    assert rc != 0
    assert receipt["verdict"] == "fail"
    assert "need_not_success:test:failure" in receipt["reasons"]


def test_need_from_different_run_fails_identity_check() -> None:
    needs = _needs_json(**{"linux-installer": {"result": "success", "run_id": RUN_ID + 1}})
    rc, receipt, _ = _run_gate(*_push_args(needs))
    assert rc != 0
    assert receipt["verdict"] == "fail"
    assert receipt["same_run"] is False
    assert any(r.startswith("identity_mismatch:linux-installer") for r in receipt["reasons"])


def test_pull_request_missing_head_and_base_fails() -> None:
    needs = json.dumps({job: {"result": "success"} for job in SIBLINGS})
    rc, receipt, _ = _run_gate(*_pr_args(needs, head=None, base=None))
    assert rc != 0
    assert receipt["verdict"] == "fail"
    assert any(r.startswith("identity_incomplete") for r in receipt["reasons"])


def test_push_missing_head_sha_fails() -> None:
    args = ["--event", "push", "--run-id", str(RUN_ID), "--needs-json", _needs_json()]
    rc, receipt, _ = _run_gate(*args)
    assert rc != 0
    assert receipt["verdict"] == "fail"
    assert any(r.startswith("identity_incomplete") for r in receipt["reasons"])


def test_unknown_event_fails_closed() -> None:
    rc, receipt, _ = _run_gate(
        "--event",
        "schedule",
        "--run-id",
        str(RUN_ID),
        "--head-sha",
        SHA_HEAD,
        "--needs-json",
        _needs_json(),
    )
    assert rc != 0
    assert receipt["verdict"] == "error"
    assert "unknown_event:schedule" in receipt["reasons"]
    assert receipt["exit_code"] == rc


def test_extra_unexpected_need_fails_closed() -> None:
    needs = _needs_json(**{"nightly-real": {"result": "success", "run_id": RUN_ID}})
    rc, receipt, _ = _run_gate(*_push_args(needs))
    assert rc != 0
    assert receipt["verdict"] == "fail"
    assert "unexpected_need:nightly-real" in receipt["reasons"]


def test_malformed_needs_json_fails_closed() -> None:
    rc, receipt, _ = _run_gate(*_push_args("not-json{{{"))
    assert rc != 0
    assert receipt["verdict"] == "error"


def test_conflicting_identity_args_fail_closed() -> None:
    args = [
        "--event",
        "push",
        "--run-id",
        str(RUN_ID),
        "--head-sha",
        SHA_HEAD,
        "--pr-head-sha",
        SHA_HEAD,
        "--needs-json",
        _needs_json(),
    ]
    rc, receipt, _ = _run_gate(*args)
    assert rc != 0
    assert receipt["verdict"] == "error"
    assert any(r.startswith("identity_conflict") for r in receipt["reasons"])


def test_need_flags_cli_form_passes() -> None:
    args = ["--event", "push", "--run-id", str(RUN_ID), "--head-sha", SHA_HEAD]
    for job in SIBLINGS:
        args += ["--need", f"{job}=success@{RUN_ID}"]
    rc, receipt, _ = _run_gate(*args)
    assert rc == 0, receipt
    assert receipt["verdict"] == "pass"
    assert receipt["same_run"] is True


def test_gate_blob_binding_reads_only_fixed_paths(tmp_path: Path) -> None:
    import hashlib

    files = (
        "scripts/premerge_gate.py", "scripts/ci_gate.sh",
        ".github/workflows/ci.yml",
    )
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    before = sorted(p.relative_to(tmp_path).as_posix()
                    for p in tmp_path.rglob("*") if p.is_file())
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "ci", "--event", "push",
         "--run-id", str(RUN_ID), "--head-sha", SHA_HEAD,
         "--needs-json", _needs_json(), "--bind-repo-blobs"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    receipt = json.loads(proc.stdout)
    assert proc.returncode == 0 and receipt["verdict"] == "pass"
    for name in files:
        data = name.encode()
        expected = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        assert receipt["gate_blobs"][name] == expected
    assert sorted(p.relative_to(tmp_path).as_posix()
                  for p in tmp_path.rglob("*") if p.is_file()) == before


def test_gate_blob_binding_missing_path_fails_closed(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "ci", "--event", "push",
         "--run-id", str(RUN_ID), "--head-sha", SHA_HEAD,
         "--needs-json", _needs_json(), "--bind-repo-blobs"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    receipt = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert receipt["verdict"] == "error"
    assert "gate_blob_binding_unavailable" in receipt["reasons"]


def test_gate_blob_binding_symlink_fails_closed(tmp_path: Path) -> None:
    files = (
        "scripts/premerge_gate.py", "scripts/ci_gate.sh",
        ".github/workflows/ci.yml",
    )
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    (tmp_path / files[0]).unlink()
    (tmp_path / files[0]).symlink_to(tmp_path / files[1])
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "ci", "--event", "push",
         "--run-id", str(RUN_ID), "--head-sha", SHA_HEAD,
         "--needs-json", _needs_json(), "--bind-repo-blobs"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    receipt = json.loads(proc.stdout)
    assert proc.returncode == 2 and receipt["verdict"] == "error"
