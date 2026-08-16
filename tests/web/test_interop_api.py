"""协调通道消息端点测试（只读展示，不触发 run）."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def _write_msg(base, direction: str, msg_id: str, body: str) -> None:
    p = base / "interop" / direction / "pending" / f"{msg_id}_{direction}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "id": msg_id,
                "from": direction.split("_")[0],
                "to": direction.split("_")[1],
                "ts": "2026-08-16T18:30:00",
                "topic": "coordinate",
                "body": body,
                "status": "pending",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_interop_messages_endpoint(build_test_engine, tmp_path, monkeypatch):
    """端点返回两个方向的 pending 协调消息（只读）."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    (tmp_path / "interop").mkdir(parents=True, exist_ok=True)
    _write_msg(tmp_path, "lfl_to_dsh", "20260816-001", "请 LFL 处理：检查 DSH 状态")
    _write_msg(tmp_path, "dsh_to_lfl", "20260816-002", "请 DSH 处理：codearts 交接")
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _make_client(engine)
    resp = client.get("/api/v1/interop/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["lfl_to_dsh"]) == 1
    assert data["lfl_to_dsh"][0]["body"] == "请 LFL 处理：检查 DSH 状态"
    assert len(data["dsh_to_lfl"]) == 1
    assert data["dsh_to_lfl"][0]["body"] == "请 DSH 处理：codearts 交接"


def test_interop_messages_empty(build_test_engine, tmp_path, monkeypatch):
    """无 pending 消息 → 空列表（前端隐藏）."""
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, _ = build_test_engine([{"content": "你好"}])
    client = _make_client(engine)
    resp = client.get("/api/v1/interop/messages")
    assert resp.status_code == 200
    assert resp.json() == {"lfl_to_dsh": [], "dsh_to_lfl": []}
