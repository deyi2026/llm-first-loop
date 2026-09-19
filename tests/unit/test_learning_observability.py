from __future__ import annotations

import json
import os
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_loop.methods.learning_journal import LearningJournal
from llm_loop.web.routes import router


def test_learning_status_exposes_durable_lifecycle_without_hidden_reasoning(tmp_path):
    data_dir = tmp_path / "data"
    journal = LearningJournal(data_dir / "sessions" / "learning" / "journal.jsonl")
    job = journal.enqueue(
        "episode:s1:1:abc",
        session_id="s1",
        source_model="glm/glm-5.3",
        trigger_facts={"rounds": 8, "tool_failures": 2},
    )
    assert job is not None
    journal.mark_started(job.job_id)
    journal.mark_saved(job.job_id, "method:probe")

    runtime_dir = data_dir / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "runtime_manifest.learning.json").write_text(
        json.dumps(
            {
                "service": "learning",
                "pid": os.getpid(),
                "started_at": "2026-09-18T18:00:00+0800",
                "git_head": "a" * 40,
                "model_ref": "glm/glm-5.3",
                "provider_id": "glm",
                "build_identity": {"display": "test"},
            }
        ),
        encoding="utf-8",
    )

    app = FastAPI()
    app.state.engine = SimpleNamespace(
        learning_journal=journal,
        learning_plane=None,
        settings=SimpleNamespace(data_dir=str(data_dir), learning_plane_enabled=True),
    )
    app.include_router(router)
    response = TestClient(app).get("/api/v1/learning/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"]["running"] is True
    assert payload["worker"]["model_ref"] == "glm/glm-5.3"
    assert payload["producer_only"] is True
    assert payload["counts"]["saved"] == 1
    row = payload["jobs"][0]
    assert row["candidate_ref"] == "method:probe"
    assert row["source_episode_ref"] == "episode:s1:1:abc"
    assert row["trigger_facts"] == {"rounds": 8, "tool_failures": 2}
    assert "reasoning" not in json.dumps(payload).lower()
