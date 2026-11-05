"""Board 只读 HTTP API 测试（DESIGN-20261105 §4.6）.

覆盖两件事:
1. GET /api/v1/coordination/board 返回 200 与契约结构字段
   （deployment / lanes / overlaps / degraded + generated_at / main_head）。
2. 只读零写副作用（A6）：调用前后 data 树（含 audit/deployments）的
   文件 sha256 摘要集合不变；audit 目录缺失时调用后仍不被创建。
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_loop.web.routes import router as web_router

BOARD_PATH = "/api/v1/coordination/board"


def _make_client(tmp_path: Path) -> tuple[TestClient, Path]:
    # tests/conftest.py 的 autouse fixture isolated_data_dir 已建 tmp_path/"data"
    # 并 chdir(tmp_path)；此处幂等复用同一目录，保持 engine.data_dir 与只读断言一致。
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    app = FastAPI()
    app.include_router(web_router)
    # workspace_root 指向确定不存在的路径：git head probe 确定性失败 → degraded 如实。
    app.state.engine = SimpleNamespace(
        settings=SimpleNamespace(data_dir=str(data_dir)),
        workspace_root=str(tmp_path / "no-such-workspace"),
    )
    return TestClient(app), data_dir


def _tree_digests(root: Path) -> dict[str, str]:
    """整树 sha256 摘要集合：内容变 / 新增 / 删除文件都会让集合不等。"""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def _lane(lane_id: str, branch: str, goal: str, paths: list[str], **extra: object) -> dict:
    row = {
        "lane_id": lane_id,
        "branch": branch,
        "worktree": "/tmp/wt-" + lane_id,
        "base_main_sha": "b4b4b4b4b4b4",
        "goal_id": goal,
        "owner_session_id": "sess-x",
        "lane_role": "main",
        "paths": paths,
        "contract_changes": [],
        "status": "active",
        "head_sha": "a1a1a1a1a1a1",
        "priority": "normal",
        "base_is_broken": False,
        "verify_ref": "",
        "close_reason": "",
        "version": 1,
        "created_at": "2026-11-05T09:00:00+08:00",
        "last_activity": "2026-11-05T10:00:00+08:00",
    }
    row.update(extra)
    return row


def test_board_contract_and_readonly_empty_audit(tmp_path: Path) -> None:
    """audit 目录存在但无账本：200 + 契约字段 + degraded 如实 + 零写。"""
    client, data_dir = _make_client(tmp_path)
    audit = data_dir / "audit"
    audit.mkdir()

    before = _tree_digests(data_dir)
    resp = client.get(BOARD_PATH)
    after = _tree_digests(data_dir)

    assert resp.status_code == 200
    body = resp.json()
    assert {"generated_at", "main_head", "deployment", "lanes", "overlaps", "degraded"} <= set(body)
    assert {"deployed_sha", "deployed_at", "deployed_phase", "in_sync", "source"} <= set(
        body["deployment"]
    )
    assert body["lanes"] == []
    assert body["overlaps"] == []
    assert isinstance(body["degraded"], list)
    assert body["deployment"]["in_sync"] is False
    # degraded 如实：workspace 非 git → main_head_unknown；deployments/ 缺失 → deployments_missing
    assert "main_head_unknown" in body["degraded"]
    assert "deployments_missing" in body["degraded"]
    # 只读（A6）：摘要集合不变（覆盖内容变 / 新增 / 删除三种写副作用）
    assert before == after
    # 未顺手创建 deployments 子目录
    assert not (audit / "deployments").exists()


def test_board_lanes_overlaps_deployment_readonly(tmp_path: Path) -> None:
    """有账本数据：lane 列表 / 部署条带 / 路径重叠投影 + 零写。"""
    client, data_dir = _make_client(tmp_path)
    audit = data_dir / "audit"
    lanes = [
        _lane("lane-aaaa0001", "feat/board-api", "goal-board", ["src/web/board/"]),
        _lane(
            "lane-bbbb0002",
            "feat/board-ui",
            "goal-ui",
            ["src/web/board/panel.tsx"],
            verify_ref="t-889",
        ),
    ]
    _write_jsonl(audit / "lanes.jsonl", lanes)
    _write_jsonl(audit / "lane_events.jsonl", [])
    _write_jsonl(
        audit / "deployments" / "web.jsonl",
        [{"ts": "2026-11-05T09:30:00+08:00", "target_sha": "b4b4b4b4b4b4", "phase": "post"}],
    )

    before = _tree_digests(data_dir)
    resp = client.get(BOARD_PATH)
    after = _tree_digests(data_dir)

    assert resp.status_code == 200
    body = resp.json()
    assert [row["lane_id"] for row in body["lanes"]] == ["lane-aaaa0001", "lane-bbbb0002"]
    assert body["lanes"][0]["goal_id"] == "goal-board"
    assert body["lanes"][1]["verify_ref"] == "t-889"
    assert body["deployment"]["deployed_sha"] == "b4b4b4b4b4b4"
    assert body["deployment"]["deployed_phase"] == "post"
    # main_head 未知（workspace probe 失败）→ in_sync 如实为 False，不伪造
    assert body["deployment"]["in_sync"] is False
    assert "main_head_unknown" in body["degraded"]
    # 路径重叠：父子路径声明 → overlaps 顶层投影非空且指向两条 lane
    assert len(body["overlaps"]) == 1
    overlap = body["overlaps"][0]
    assert {overlap["a"], overlap["b"]} == {"lane-aaaa0001", "lane-bbbb0002"}
    assert "src/web/board/panel.tsx" in overlap["shared_paths"]
    # 只读（A6）
    assert before == after


def test_board_audit_missing_degrades_without_mkdir(tmp_path: Path) -> None:
    """audit 目录缺失：降级为 audit_missing 且绝不 mkdir（A6 最硬证据）。"""
    client, data_dir = _make_client(tmp_path)  # 不创建 audit 目录

    before = _tree_digests(data_dir)
    resp = client.get(BOARD_PATH)
    after = _tree_digests(data_dir)

    assert resp.status_code == 200
    body = resp.json()
    assert body["lanes"] == []
    assert "audit_missing" in body["degraded"]
    assert not (data_dir / "audit").exists()
    assert before == after
