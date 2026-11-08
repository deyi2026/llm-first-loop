"""U5 子进程：经监督通道执行一次非幂等 fs.write，在副作用落盘后卡住，等父进程 kill -9。

``Executor._atomic_write`` 先真实写入并 ``os.replace``，再 sleep——这精确模拟
「副作用已经发生、回执尚未落盘」的崩溃窗口。父进程看到目标文件后立即 SIGKILL。
"""

from __future__ import annotations

import base64
import sys
import time
from datetime import timedelta
from pathlib import Path


def main() -> int:
    src, data_dir, write_root, target = sys.argv[1:5]
    sys.path.insert(0, src)

    from llm_loop.peer.admission import AdmissionStore
    from llm_loop.peer.artifacts import ArtifactStore
    from llm_loop.peer.executor import Executor
    from llm_loop.peer.models import GrantRecord, iso, now_local
    from llm_loop.peer.service import PeerService
    from llm_loop.peer.store import PeerStore

    data = Path(data_dir)
    root = Path(write_root)
    original = Executor._atomic_write

    def write_then_hang(target_path: str, payload: bytes) -> None:
        original(target_path, payload)
        time.sleep(120)

    Executor._atomic_write = staticmethod(write_then_hang)

    store = PeerStore(data)
    service = PeerService(
        store=store,
        admissions=AdmissionStore(data),
        artifacts=ArtifactStore(data / "artifacts"),
        node_id="deepin-01",
        write_root=str(root),
        supervision_enabled=True,
        supervision_ttl_s=120,
    )
    store.issue_grant(
        GrantRecord(
            grant_id="gr_U5KILL000001",
            node_id="deepin-01",
            issued_by={"ingress": "feishu", "human": "lfl"},
            issued_at=iso(now_local()),
            expires_at=iso(now_local() + timedelta(hours=1)),
            state="active",
            allowed_kinds=("fs.read", "fs.list", "fs.write"),
            allowed_paths=(str(root),),
            max_concurrency=2,
            max_tasks_total=5,
        )
    )
    receipt = service.submit(
        {
            "schema": "lfl.peer.v1",
            "effect_id": "eff_u5kill0001",
            "kind": "fs.write",
            "params": {
                "path": str(target),
                "content_b64": base64.b64encode(b"u5-partial-side-effect" * 8).decode("ascii"),
            },
            "deadline_s": 30,
        }
    )
    task_id = receipt["task_id"]
    service.issue_supervision_ticket(task_id, issued_by="u5")
    service.resume_supervised(task_id, decided_by="u5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
