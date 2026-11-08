"""U5 重测（T9-b）：非幂等 kind 执行中被 kill -9 → unknown_outcome 且不自动重跑。

T9-b 之前 P1 只有只读 kind，造不出「已产生副作用、结果未知」的真实场景；
fs.write 上线后这道验收才可执行。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from llm_loop.peer.admission import AdmissionStore
from llm_loop.peer.artifacts import ArtifactStore
from llm_loop.peer.service import PeerService
from llm_loop.peer.store import PeerStore

REPO_ROOT = Path(__file__).resolve().parents[3]
CHILD = Path(__file__).with_name("u5_child.py")


def _wait(predicate, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _running_tasks(data: Path) -> list[dict]:
    payload = json.loads((data / "tasks.json").read_text(encoding="utf-8"))
    return [item for item in payload["items"] if item["state"] == "running"]


def test_killed_non_idempotent_write_recovers_unknown_outcome(tmp_path: Path) -> None:
    data = tmp_path / "peer"
    root = tmp_path / "wr"
    root.mkdir()
    target = root / "payload.bin"

    child = subprocess.Popen(
        [
            sys.executable,
            str(CHILD),
            str(REPO_ROOT / "src"),
            str(data),
            str(root),
            str(target),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert _wait(lambda: target.exists() and target.stat().st_size > 0), (
            "副作用未落盘；子进程 stderr: " + child.stderr.read().decode("utf-8", "replace")
        )
        running = _running_tasks(data)
        assert len(running) == 1, f"期望恰有一个 running 任务，实际 {running}"
        task_id = running[0]["task_id"]
        digest_before = hashlib.sha256(target.read_bytes()).hexdigest()
        child.kill()
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)

    # 重启：running 的非幂等任务必须收敛为 unknown_outcome，不能声称成功或失败
    store = PeerStore(data)
    service = PeerService(
        store=store,
        admissions=AdmissionStore(data),
        artifacts=ArtifactStore(data / "artifacts"),
        node_id="deepin-01",
        write_root=str(root),
    )
    recovered = service.recover_interrupted()
    assert [task.task_id for task in recovered] == [task_id]
    assert recovered[0].state == "unknown_outcome"

    task = store.get_task(task_id)
    assert task is not None and task.state == "unknown_outcome"
    # 不自动重跑：副作用只发生一次，文件内容未被二次写覆盖
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest_before
    # 额度不回滚：一次未知结果仍计一次任务消耗
    assert store.get_grant("gr_U5KILL000001").tasks_used == 1
