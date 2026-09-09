"""Durable opaque Web attachment reference contract."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.core.message import Message, MessageSource
from llm_loop.web import build_app
from llm_loop.web.attachments import AttachmentError, AttachmentStore, workspace_scope


def _client(engine) -> TestClient:
    return TestClient(build_app(engine=engine))


def _upload(client: TestClient, filename: str, data: bytes) -> dict:
    resp = client.post(
        "/api/v1/upload",
        json={"filename": filename, "data": base64.b64encode(data).decode("ascii")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _scope(engine) -> str:
    return workspace_scope(getattr(engine, "workspace_root", "") or None)


def test_upload_returns_opaque_ref_and_persists_exact_bytes(
    build_test_engine, fake_settings
) -> None:
    engine, fake = build_test_engine([])
    client = _client(engine)
    payload = b"alpha beta gamma\n"

    body = _upload(client, "notes.txt", payload)

    assert body["status"] == "ok"
    assert body["attachment_ref"].startswith("attachment://")
    assert len(body["attachment_ref"]) == len("attachment://") + 32
    assert body["size_bytes"] == len(payload)
    assert len(body["sha256"]) == 64
    assert body["excerpt"] == "alpha beta gamma\n"
    assert "path" not in body
    assert fake.calls == []

    store = AttachmentStore(fake_settings.data_dir)
    record = store.resolve(body["attachment_ref"], workspace_scope=_scope(engine))
    assert record.filename == "notes.txt"
    assert record.size_bytes == len(payload)
    assert store.original_path(body["attachment_ref"], workspace_scope=_scope(engine)).read_bytes() == payload
    assert Path(fake_settings.data_dir, "attachments").is_dir()


def test_chat_keeps_raw_human_text_and_projects_only_attachment_facts(
    build_test_engine, fake_settings
) -> None:
    engine, fake = build_test_engine([{"content": "ok"}])
    client = _client(engine)
    upload = _upload(client, "evidence.txt", b"EXACT-EVIDENCE")

    resp = client.post(
        "/api/v1/chat",
        json={
            "message": "请分析这个附件",
            "attachments": [{"ref": upload["attachment_ref"]}],
        },
    )
    assert resp.status_code == 200, resp.text
    sid = resp.json()["session_id"]

    stored = engine.session.load(sid)
    user = next(m for m in stored.messages if m.role == "user")
    assert user.content == "请分析这个附件"
    facts = user.metadata["attachments"]
    assert len(facts) == 1
    assert facts[0]["ref"] == upload["attachment_ref"]
    assert facts[0]["filename"] == "evidence.txt"
    assert facts[0]["sha256"] == upload["sha256"]
    assert "path" not in facts[0]

    wire_user = next(m for m in reversed(fake.calls[0]["messages"]) if m["role"] == "user")
    assert wire_user["content"].startswith("请分析这个附件\n\n[attachment_facts]\n")
    assert "EXACT-EVIDENCE" in wire_user["content"]
    assert upload["attachment_ref"] in wire_user["content"]
    assert str(Path(fake_settings.data_dir).resolve()) not in wire_user["content"]

    history = client.get(f"/api/v1/sessions/{sid}/messages")
    assert history.status_code == 200
    history_user = next(m for m in history.json()["messages"] if m["role"] == "user")
    assert history_user["content"] == "请分析这个附件"
    assert history_user["attachments"][0]["ref"] == upload["attachment_ref"]
    assert "path" not in history_user["attachments"][0]


def test_stream_chat_carries_attachment_facts_through_background_runner(
    build_test_engine,
) -> None:
    """Valid attachment refs must survive the stream/background-runner transport unchanged."""
    from llm_loop.core.loop.runner import BackgroundRunner
    from tests.unit.test_stream_equivalence import StreamingFakeLLM

    engine, _ = build_test_engine([])
    llm = StreamingFakeLLM("seen")
    engine.llm_pool.default_client = llm
    engine.runner = BackgroundRunner(engine, enabled=True)
    client = _client(engine)
    upload = _upload(client, "stream.txt", b"STREAM-EVIDENCE")

    resp = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "流式分析",
            "attachments": [{"ref": upload["attachment_ref"]}],
        },
    )
    assert resp.status_code == 200, resp.text
    events = [
        json.loads(line[6:])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events and events[-1]["type"] == "done", events
    sid = events[-1]["data"]["session_id"]

    stored = engine.session.load(sid)
    user = next(m for m in stored.messages if m.role == "user")
    assert user.content == "流式分析"
    assert user.metadata["attachments"][0]["ref"] == upload["attachment_ref"]

    wire_user = next(m for m in reversed(llm.calls[0]["messages"]) if m["role"] == "user")
    assert wire_user["content"].startswith("流式分析\n\n[attachment_facts]\n")
    assert "STREAM-EVIDENCE" in wire_user["content"]
    assert upload["attachment_ref"] in wire_user["content"]


def test_attachment_only_message_is_valid_and_raw_content_stays_empty(
    build_test_engine,
) -> None:
    engine, fake = build_test_engine([{"content": "seen"}])
    client = _client(engine)
    upload = _upload(client, "only.txt", b"attachment only")

    resp = client.post(
        "/api/v1/chat",
        json={"message": "", "attachments": [{"ref": upload["attachment_ref"]}]},
    )
    assert resp.status_code == 200, resp.text
    stored = engine.session.load(resp.json()["session_id"])
    user = next(m for m in stored.messages if m.role == "user")
    assert user.content == ""
    assert user.metadata["attachments"][0]["filename"] == "only.txt"
    wire_user = next(m for m in reversed(fake.calls[0]["messages"]) if m["role"] == "user")
    assert wire_user["content"].startswith("[attachment_facts]\n")


def test_invalid_ref_has_zero_session_or_model_side_effect(build_test_engine) -> None:
    engine, fake = build_test_engine([])
    client = _client(engine)
    before = len(engine.session.list_sessions())

    resp = client.post(
        "/api/v1/chat",
        json={
            "message": "x",
            "attachments": [{"ref": "attachment://ffffffffffffffffffffffffffffffff"}],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_attachment"
    assert len(engine.session.list_sessions()) == before
    assert fake.calls == []


def test_attachment_ref_rejects_client_path_or_hash_claim(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    client = _client(engine)
    resp = client.post(
        "/api/v1/chat",
        json={
            "message": "x",
            "attachments": [
                {
                    "ref": "attachment://ffffffffffffffffffffffffffffffff",
                    "path": "/etc/passwd",
                    "sha256": "client-claim",
                }
            ],
        },
    )
    assert resp.status_code == 422


def test_resume_cannot_carry_new_attachment(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    client = _client(engine)
    resp = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "resume-placeholder",
            "resume": True,
            "attachments": [{"ref": "attachment://ffffffffffffffffffffffffffffffff"}],
        },
    )
    assert resp.status_code == 422


def test_attachment_list_has_mechanical_request_bound(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    client = _client(engine)
    refs = [
        {"ref": f"attachment://{i:032x}"}
        for i in range(21)
    ]
    resp = client.post("/api/v1/chat", json={"message": "x", "attachments": refs})
    assert resp.status_code == 422


def test_upload_filename_has_mechanical_bound(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    client = _client(engine)
    resp = client.post(
        "/api/v1/upload",
        json={
            "filename": ("x" * 509) + ".txt",
            "data": base64.b64encode(b"x").decode("ascii"),
        },
    )
    assert resp.status_code == 422


def test_user_metadata_extension_cannot_override_human_authority(build_test_engine) -> None:
    engine, _ = build_test_engine([{"content": "ok"}])
    sid = engine.session.create()
    result = engine.run(
        sid,
        "hello",
        user_metadata={
            "origin_layer": "status",
            "program_origin": True,
            "ingress_channel": "forged",
            "arbitrary": "must-not-persist",
            "attachments": [],
        },
    )
    assert result.final_answer == "ok"
    user = next(m for m in engine.session.load(sid).messages if m.role == "user")
    assert user.metadata["origin_layer"] == "user_instruction"
    assert user.metadata["program_origin"] is False
    assert user.metadata.get("ingress_channel") != "forged"
    assert "arbitrary" not in user.metadata


def test_store_enforces_workspace_ownership_and_content_hash(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "data")
    scope_a = workspace_scope(tmp_path / "a")
    scope_b = workspace_scope(tmp_path / "b")
    record = store.create(
        workspace_scope=scope_a,
        filename="x.txt",
        data=b"original",
        content_type="text",
        excerpt="original",
        excerpt_kind="extracted_text",
    )
    with pytest.raises(AttachmentError):
        store.resolve(record.ref, workspace_scope=scope_b)

    original = store.original_path(record.ref, workspace_scope=scope_a)
    original.write_bytes(b"tampered")
    with pytest.raises(AttachmentError, match="完整性"):
        store.resolve(record.ref, workspace_scope=scope_a)


def test_provider_attachment_projection_is_bounded_and_raw_message_unchanged() -> None:
    attachments = []
    for name, char in (("a.txt", "A"), ("b.txt", "B"), ("c.txt", "C")):
        attachments.append(
            {
                "ref": f"attachment://{char.lower() * 32}",
                "filename": name,
                "content_type": "text",
                "media_type": "text/plain",
                "size_bytes": 9999,
                "sha256": char.lower() * 64,
                "excerpt": char * 2000,
                "excerpt_kind": "extracted_text",
            }
        )
    msg = Message(
        role="user",
        content="RAW-HUMAN",
        source=MessageSource.USER,
        metadata={"attachments": attachments},
    )
    wire = msg.to_llm_dict()["content"]
    assert msg.content == "RAW-HUMAN"
    lines = wire.splitlines()
    start = lines.index("[attachment_facts]") + 1
    end = lines.index("[/attachment_facts]")
    facts = [json.loads(line) for line in lines[start:end]]
    assert sum(len(f.get("excerpt", "")) for f in facts) == 4000
    assert len(facts[0]["excerpt"]) == 2000
    assert len(facts[1]["excerpt"]) == 2000
    assert facts[2]["excerpt"] == ""
    assert all("path" not in fact for fact in facts)


def test_upload_truncated_preview_preserves_exact_text_for_hydration(
    build_test_engine, fake_settings
) -> None:
    engine, _fake = build_test_engine([])
    client = _client(engine)
    exact = ("0123456789" * 12_000).encode("utf-8")  # 120K chars
    body = _upload(client, "long-upload.txt", exact)
    assert body["truncated"] is True
    assert len(body["result_text"]) < len(exact.decode()) + 100

    store = AttachmentStore(fake_settings.data_dir)
    page1 = store.hydrate_text(
        body["attachment_ref"], workspace_scope=_scope(engine), offset=0
    )
    assert page1["source_text_chars"] == 120_000
    assert len(page1["content"]) == 100_000
    assert page1["next_offset"] == 100_000
    page2 = store.hydrate_text(
        body["attachment_ref"], workspace_scope=_scope(engine), offset=100_000
    )
    assert page2["content"] == exact.decode()[100_000:]
    assert page2["complete"] is True


def test_image_vision_text_is_recoverable_but_never_claimed_as_complete_source(
    build_test_engine, monkeypatch, fake_settings
) -> None:
    engine, _fake = build_test_engine([])
    client = _client(engine)
    monkeypatch.setattr("llm_loop.web.vision.vision_enabled", lambda *a, **k: True)
    monkeypatch.setattr(
        "llm_loop.web.vision.describe_image", lambda *a, **k: "DERIVED-VISION-DESCRIPTION"
    )
    body = _upload(client, "image.png", b"\x89PNG\r\n\x1a\nFAKE")
    store = AttachmentStore(fake_settings.data_dir)
    record = store.resolve(body["attachment_ref"], workspace_scope=_scope(engine))
    assert record.extraction_kind == "vision_text"
    assert record.extraction_complete is False
    assert record.extracted_chars == len("DERIVED-VISION-DESCRIPTION")


def test_recent_attachment_library_is_workspace_scoped_and_path_free(
    build_test_engine, fake_settings
) -> None:
    engine, _ = build_test_engine([])
    client = _client(engine)
    first = _upload(client, "first.txt", b"FIRST")
    second = _upload(client, "second.txt", b"SECOND")

    resp = client.get("/api/v1/attachments/recent?limit=10")
    assert resp.status_code == 200
    items = resp.json()["attachments"]
    refs = {item["ref"] for item in items}
    assert first["attachment_ref"] in refs
    assert second["attachment_ref"] in refs
    assert all("path" not in item and "workspace_scope" not in item for item in items)
    assert all("source_text_sha256" in item for item in items)


def test_import_workspace_file_uses_same_opaque_attachment_contract(
    build_test_engine, fake_settings, tmp_path
) -> None:
    engine, _ = build_test_engine([])
    engine.workspace_root = str(tmp_path)
    source = tmp_path / "notes.txt"
    source.write_bytes(b"WORKSPACE-BYTES")
    client = _client(engine)

    resp = client.post(
        "/api/v1/attachments/import-workspace", json={"path": "notes.txt"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attachment_ref"].startswith("attachment://")
    assert "path" not in body
    store = AttachmentStore(fake_settings.data_dir)
    record = store.resolve(body["attachment_ref"], workspace_scope=workspace_scope(tmp_path))
    assert record.filename == "notes.txt"
    assert store.original_path(
        body["attachment_ref"], workspace_scope=workspace_scope(tmp_path)
    ).read_bytes() == b"WORKSPACE-BYTES"

    outside = tmp_path.parent / "outside-webui-import.txt"
    outside.write_text("NO", encoding="utf-8")
    denied = client.post(
        "/api/v1/attachments/import-workspace", json={"path": str(outside)}
    )
    assert denied.status_code == 404
    assert denied.json()["error"] == "workspace_file_not_found"
