"""P1-3 补洞回归（2026-10-25）：敏感文件不得被重命名洗白.

红队实测：`.env` PUT /api/v1/fs/rename → `.env.example` 后，preview 的模板后缀
豁免（.example/.sample/...）会放行读取，敏感内容外泄。修复：源路径命中
security_guard.sensitive_path_reason 即 403 sensitive_path_blocked。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app


@pytest.fixture()
def client(tmp_path):
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMClient
    from llm_loop.tools.registry import ToolRegistry

    data_dir = tmp_path / "data"
    settings = Settings(
        llm_api_key="k", llm_base_url="http://t", llm_model="m", data_dir=str(data_dir)
    )
    (tmp_path / "ws").mkdir(exist_ok=True)
    engine = LoopEngine(
        llm_client=LLMClient(api_key="k", base_url="http://t", model="m"),
        registry=ToolRegistry(),
        memory=None,
        session=SessionStore(data_dir / "sessions"),
        settings=settings,
    )
    engine.workspace_root = str(tmp_path / "ws")
    app = build_app(engine=engine)
    app.state.engine = engine
    return TestClient(app), engine


def test_rename_env_to_template_is_blocked(client, tmp_path):
    cli, _ = client
    env = tmp_path / "ws" / ".env"
    env.write_text("SECRET=top", encoding="utf-8")

    r = cli.put("/api/v1/fs/rename", params={"path": ".env", "new_name": ".env.example"})
    assert r.status_code == 403, r.text
    assert r.json()["error"] == "sensitive_path_blocked"
    assert env.exists(), "被拒绝的重命名不得产生副作用"


def test_rename_normal_file_still_allowed(client, tmp_path):
    cli, _ = client
    src = tmp_path / "ws" / "notes.txt"
    src.write_text("hi", encoding="utf-8")
    r = cli.put("/api/v1/fs/rename", params={"path": "notes.txt", "new_name": "notes2.txt"})
    assert r.status_code == 200, r.text
    assert (tmp_path / "ws" / "notes2.txt").exists()
