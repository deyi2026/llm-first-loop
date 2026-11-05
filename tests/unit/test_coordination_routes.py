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


def _loopback_request():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": BOARD_PATH,
        "headers": [],
        "client": ("127.0.0.1", 5555),
        "server": ("127.0.0.1", 8903),
        "scheme": "http",
        "query_string": b"",
    }
    return Request(scope)


def test_loopback_exemption_is_the_compensating_control(monkeypatch) -> None:
    """替代控制实证（RULE-AI-35）：删除 handler 内二次鉴权后留下的那道闸

    装配层 `app.include_router(router, dependencies=[Depends(require_api_key)])`
    的口径由 `request_auth_required(request)` 决定——它对 loopback 直连返回
    False（放行），与 env 级 `auth_required()` 语义不同。这里直接实测该口径，
    证明 401 的移除不是"少一道闸"，而是"两个判定收敛成一个"。
    """
    from llm_loop.web.auth import (
        auth_required,
        request_auth_required,
        request_is_trusted_local,
        require_api_key,
    )

    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")  # 公网策略开启
    # 前置：env 级判定此刻为 True（说明下面拿到 False 不是"策略本来就关"
    # 造成的假阳性，而是 loopback 豁免真的发生）。
    assert auth_required() is True

    req = _loopback_request()
    assert request_is_trusted_local(req) is True
    assert request_auth_required(req) is False
    require_api_key(credentials=None, request=req)  # 不抛 = 放行


def test_public_origin_is_not_exempt(monkeypatch) -> None:
    """反向实证：非 loopback 来源必须仍被要求鉴权（豁免不得外溢）。

    本用例**不带任何转发 header**：只把来源换成公网 IP，保证与
    `test_loopback_exemption_*` 相比只有一个变量不同（来源），
    避免把 header 语义和来源语义混在一起判。
    """
    from starlette.requests import Request

    from llm_loop.web.auth import request_auth_required

    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    scope = {
        "type": "http",
        "method": "GET",
        "path": BOARD_PATH,
        "headers": [],
        "client": ("203.0.113.9", 443),
        "server": ("203.0.113.9", 443),
        "scheme": "https",
        "query_string": b"",
    }
    assert request_auth_required(Request(scope)) is True


def test_no_dangling_auth_import() -> None:
    """P2-2 实证：删掉 import 后模块里不得残留 auth_required/request_authenticated。"""
    from llm_loop.web import coordination_routes as mod

    assert not hasattr(mod, "auth_required")
    assert not hasattr(mod, "request_authenticated")


def test_spoofed_forwarded_for_revokes_loopback_trust(monkeypatch) -> None:
    """P2-1 实证：伪造 `X-Forwarded-For: 127.0.0.1` 不得复活 loopback 豁免。

    `request_is_trusted_local` 的规则是「任何转发标记都撤销豁免」。本用例
    把 host/peer 都设成 loopback、只加一个伪造 header：若实现改成「看 XFF
    是否等于 loopback 就放行」，这里会立刻变红——这正是 r8 审查指出的
    「XFF 未被区分」的风险点。
    """
    from starlette.requests import Request

    from llm_loop.web.auth import request_auth_required, request_is_trusted_local

    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    scope = {
        "type": "http",
        "method": "GET",
        "path": BOARD_PATH,
        "headers": [(b"x-forwarded-for", b"127.0.0.1")],
        "client": ("127.0.0.1", 5555),
        "server": ("127.0.0.1", 8903),
        "scheme": "http",
        "query_string": b"",
    }
    req = Request(scope)
    assert request_is_trusted_local(req) is False
    assert request_auth_required(req) is True

def _make_mounted_app(tmp_path: Path) -> FastAPI:
    """按 web/__init__.py 的真实装配方式挂载 main router（含 require_api_key）。

    与 `_make_client` 的区别：那个不带依赖，只测 handler；这个带装配层依赖，
    用来证明「删掉 handler 内二次鉴权后，闸仍在装配层」。
    """
    from fastapi import Depends

    from llm_loop.web.auth import require_api_key

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    app = FastAPI()
    app.include_router(web_router, dependencies=[Depends(require_api_key)])
    app.state.engine = SimpleNamespace(
        settings=SimpleNamespace(data_dir=str(data_dir)),
        workspace_root=str(tmp_path / "no-such-workspace"),
    )
    return app


def _asgi_get(app: FastAPI, path: str, *, client_host: str):
    """用 ASGITransport 设置真实 scope["client"]，模拟 loopback/公网来源。"""
    import asyncio

    import httpx

    transport = httpx.ASGITransport(app=app, client=(client_host, 1234))

    async def _go():
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{client_host}:8903"
        ) as client:
            return await client.get(path)

    return asyncio.run(_go())


def test_board_200_through_real_assembly_mount(tmp_path: Path, monkeypatch) -> None:
    """P1 正证：装配层 require_api_key + loopback 直连无凭据 → Board 200。

    这是「删掉 handler 内 401 后仍然安全」的端到端证据：闸没有消失，
    只是从 handler 移到装配层，且对本机 WebUI 放行。
    """
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    app = _make_mounted_app(tmp_path)

    resp = _asgi_get(app, BOARD_PATH, client_host="127.0.0.1")

    assert resp.status_code == 200
    body = resp.json()
    assert {"deployment", "lanes", "overlaps", "degraded"} <= set(body)


def test_board_401_through_real_assembly_mount_from_public_origin(
    tmp_path: Path, monkeypatch
) -> None:
    """P1 反证：同一装配下，公网来源无凭据 → 401（豁免不外溢）。

    必须先配置凭据：`require_api_key` 在 request_auth_required=True 且
    auth_configured()=False 时走 fail-closed 503（auth.py:658），
    那样测到的是"未配置"而非"未认证"，语义完全不同。
    """
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("WEB_API_KEY", "test-key-0123456789abcdef")
    app = _make_mounted_app(tmp_path)

    resp = _asgi_get(app, BOARD_PATH, client_host="203.0.113.9")

    assert resp.status_code == 401
