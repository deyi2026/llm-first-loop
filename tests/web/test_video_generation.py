"""H3 API boundaries and real worker lifecycle; no real model/API calls."""

from __future__ import annotations

import hashlib
import io
import os
import signal
import sys
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from llm_loop.config import load_settings
from llm_loop.video.runtime import (
    VideoConfig,
    VideoError,
    VideoRequest,
    VideoRuntime,
    atomic_json,
    build_command,
    file_lock,
)
from llm_loop.web import build_app


@pytest.fixture
def video_client(build_test_engine, tmp_path, monkeypatch):
    engine, _ = build_test_engine([])
    engine.settings = replace(
        engine.settings,
        video_model_root=str(tmp_path / "models"),
        video_sd_cli=str(tmp_path / "missing-sd-cli"),
    )
    runtime = VideoRuntime(
        engine.settings.data_dir,
        model_root=engine.settings.video_model_root,
        sd_cli=engine.settings.video_sd_cli,
    )
    return TestClient(build_app(engine=engine)), runtime


def test_video_paths_use_canonical_settings_not_process_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LFL_VIDEO_MODEL_ROOT", "/wrong/models")
    monkeypatch.setenv("LFL_VIDEO_SD_CLI", "/wrong/sd-cli")
    settings = load_settings({
        "LLM_API_KEY": "fixture-key-never-sent",
        "LLM_BASE_URL": "https://video.invalid/v1",
        "DATA_DIR": str(tmp_path / "data"),
        "LFL_VIDEO_MODEL_ROOT": str(tmp_path / "models"),
        "LFL_VIDEO_SD_CLI": str(tmp_path / "sd-cli"),
        "LFL_LFRT_CLI": "/explicit/lfrt",
    })
    runtime = VideoRuntime(
        tmp_path / "data", model_root=settings.video_model_root, sd_cli=settings.video_sd_cli
    )
    assert runtime.models == tmp_path / "models"
    assert runtime.sd_cli == str(tmp_path / "sd-cli")
    assert settings.lfrt_cli == "/explicit/lfrt"


def test_configuration_and_prerequisites(video_client, tmp_path):
    client, runtime = video_client
    status = client.get("/api/v1/video").json()
    assert not status["prerequisites_ready"]
    assert "H3 视频权重" in status["missing"]
    assert status["version"] == "missing"
    cfg = status["config"]
    cfg["diffusion_model"] = "elsewhere/h3.gguf"
    response = client.put(
        "/api/v1/video/config", json={"config": cfg, "expected_version": "missing"}
    )
    assert response.status_code == 200
    assert runtime.config()[0].diffusion_model == cfg["diffusion_model"]
    assert (
        client.put(
            "/api/v1/video/config", json={"config": cfg, "expected_version": "missing"}
        ).status_code
        == 409
    )
    assert client.post("/api/v1/video/jobs", json={"prompt": "cat"}).status_code == 503


def test_component_escape_and_symlink_are_rejected(video_client, tmp_path):
    client, runtime = video_client
    cfg = VideoConfig().model_dump()
    for name in ("../../escape.gguf", str(tmp_path / "outside.gguf")):
        cfg["diffusion_model"] = name
        assert (
            client.put(
                "/api/v1/video/config", json={"config": cfg, "expected_version": "missing"}
            ).status_code
            == 400
        )
    runtime.models.mkdir(parents=True)
    (runtime.models / "link.gguf").symlink_to(tmp_path / "outside.gguf")
    cfg["diffusion_model"] = "link.gguf"
    assert (
        client.put(
            "/api/v1/video/config", json={"config": cfg, "expected_version": "missing"}
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "body",
    [
        {"prompt": " "},
        {"prompt": "cat", "width": 641},
        {"prompt": "cat", "frames": 25},
        {"prompt": "cat", "steps": 0},
        {"prompt": "cat", "command": "echo unsafe"},
    ],
)
def test_mechanical_request_validation(video_client, body):
    assert video_client[0].post("/api/v1/video/jobs", json=body).status_code == 422


def test_command_preserves_prompt_and_h3_contract(tmp_path):
    prompt = 'cat "quoted"; $(touch /tmp/never-run)\nSound: rain'
    request = VideoRequest(prompt=prompt, references=["a" * 32])
    argv = build_command(
        "/fake/sd-cli",
        VideoConfig(),
        request,
        tmp_path,
        tmp_path / "raw.webm",
        [tmp_path / "ref.png"],
    )
    assert argv[argv.index("--prompt") + 1] == prompt
    assert argv[argv.index("--cfg-scale") + 1] == "1.0"
    assert argv[argv.index("--mode") + 1] == "vid_gen"
    assert argv[argv.index("--fps") + 1] == "24"
    assert argv[argv.index("--flash-attn") + 1] == "off,te=on"
    assert argv[argv.index("--backend") + 1] == "te=cpu"
    assert "--audio-vae" in argv and "--offload-to-cpu" in argv
    assert argv[-2:] == ["--ref-image", str(tmp_path / "ref.png")]


def test_reference_upload_and_invalid_resource_ids(video_client):
    client, runtime = video_client
    data = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(data, format="PNG")
    response = client.post(
        "/api/v1/video/references",
        files={"file": ("../../unsafe.png", data.getvalue(), "image/png")},
    )
    assert response.status_code == 201
    assert runtime.reference_path(response.json()["id"]).is_file()
    assert response.json()["sha256"] == hashlib.sha256(data.getvalue()).hexdigest()
    assert (
        client.get("/api/v1/video/references/" + response.json()["id"] + "/source").content
        == data.getvalue()
    )
    assert (
        client.post(
            "/api/v1/video/references", files={"file": ("fake.png", b"invalid", "image/png")}
        ).status_code
        == 400
    )
    assert client.get("/api/v1/video/jobs/not-a-job").status_code == 404
    assert client.get(f"/api/v1/video/jobs/{'a' * 32}/files/output").status_code == 404


def test_reference_store_works_without_web_transport(tmp_path):
    runtime = VideoRuntime(tmp_path / "data", model_root=tmp_path / "models")
    data = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(data, format="PNG")
    facts = runtime.store_reference(data.getvalue())
    original, media_type = runtime.reference_original(facts["id"])
    assert original.read_bytes() == data.getvalue()
    assert media_type == "image/png"
    original.unlink()
    with pytest.raises(VideoError, match="参考图不存在"):
        runtime.reference_original(facts["id"])


def test_slot_and_interrupted_recovery(video_client):
    _, runtime = video_client
    job_id = "a" * 32
    atomic_json(
        runtime.job_dir(job_id) / "job.json", {"id": job_id, "created_at": 1, "status": "running"}
    )
    with file_lock(runtime.root / "execution.lock"):
        assert runtime.job(job_id)["status"] == "running"
        with (
            pytest.raises(VideoError, match="已有视频任务"),
            file_lock(runtime.root / "execution.lock", blocking=False),
        ):
            pass
    assert runtime.job(job_id)["status"] == "interrupted"


def _fake_backend(video_client, tmp_path, monkeypatch, *, sleeping=False, rc=0):
    client, runtime = video_client
    if os.name != "posix":
        pytest.skip("POSIX local-video backend")
    for name in ("diffusion_model", "text_encoder", "video_vae", "audio_vae"):
        path = runtime.model_path(getattr(VideoConfig(), name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test fixture, not real weights")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    scripts = {
        "sd-cli": "import pathlib,sys,time\n"
        + "import os\npathlib.Path(sys.argv[sys.argv.index('--output')+1]).with_name('backend.pid').write_text(str(os.getpid()))\n"
        + ("time.sleep(30)\n" if sleeping else "")
        + f"pathlib.Path(sys.argv[sys.argv.index('--output')+1]).write_bytes(b'test video')\nsys.exit({rc})\n",
        "ffmpeg": "import pathlib,sys\npathlib.Path(sys.argv[-1]).write_bytes(b'test mp4 fixture')\n",
        "ffprobe": 'print(\'{"streams":[{"codec_type":"video","width":640,"height":384},{"codec_type":"audio"}],"format":{"duration":"2.333"}}\')\n',
    }
    for name, script in scripts.items():
        path = bindir / name
        path.write_text(f"#!{sys.executable}\n{script}")
        path.chmod(0o700)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    runtime.sd_cli = str(bindir / "sd-cli")
    engine = client.app.state.engine
    engine.settings = replace(engine.settings, video_sd_cli=runtime.sd_cli)
    # Detached worker AND guardian must resolve this source despite a foreign env.
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "foreign-source"))


def _terminal(runtime, job_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = runtime.job(job_id)
        if record["status"] not in {"queued", "running"}:
            return record
        time.sleep(0.05)
    pytest.fail("worker did not settle")


def test_detached_worker_durable_success(video_client, tmp_path, monkeypatch):
    client, runtime = video_client
    _fake_backend(video_client, tmp_path, monkeypatch)
    response = client.post("/api/v1/video/jobs", json={"prompt": "cat and native audio"})
    assert response.status_code == 202
    job_id = response.json()["id"]
    # A new facade simulates a Web reconnect: no in-memory job state is required.
    record = _terminal(VideoRuntime(runtime.root.parent), job_id)
    assert record["status"] == "done", record
    assert record["output"]["sha256"] == hashlib.sha256(b"test mp4 fixture").hexdigest()
    assert client.get(f"/api/v1/video/jobs/{job_id}/files/output").content == b"test mp4 fixture"
    saved = client.get(f"/api/v1/video/jobs/{job_id}/files/request").json()
    assert saved["request"]["prompt"] == "cat and native audio"
    assert (runtime.job_dir(job_id) / "execution.json").exists()


def test_cancel_owns_process_and_releases_slot(video_client, tmp_path, monkeypatch):
    client, runtime = video_client
    _fake_backend(video_client, tmp_path, monkeypatch, sleeping=True)
    first = client.post("/api/v1/video/jobs", json={"prompt": "slow"})
    assert first.status_code == 202
    job_id = first.json()["id"]
    assert client.post("/api/v1/video/jobs", json={"prompt": "second"}).status_code == 409
    assert client.post(f"/api/v1/video/jobs/{job_id}/cancel").status_code == 202
    assert _terminal(runtime, job_id)["status"] == "cancelled"
    with file_lock(runtime.root / "execution.lock", blocking=False):
        pass
    assert client.get(f"/api/v1/video/jobs/{job_id}/files/output").status_code == 409


def test_backend_failure_is_not_success_or_retry(video_client, tmp_path, monkeypatch):
    client, runtime = video_client
    _fake_backend(video_client, tmp_path, monkeypatch, rc=7)
    response = client.post("/api/v1/video/jobs", json={"prompt": "failure"})
    record = _terminal(runtime, response.json()["id"])
    assert record["status"] == "failed"
    assert "7" in record["error"]
    assert record["output"] is None


def test_video_inherits_public_auth_and_origin_guards(build_test_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_API_KEY", "video-auth-fixture")
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("WEB_AUTH_REQUIRE", "1")
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("LFL_VIDEO_MODEL_ROOT", str(tmp_path / "models"))
    engine, _ = build_test_engine([])
    client = TestClient(build_app(engine=engine))
    assert client.get("/api/v1/video").status_code == 401
    assert client.post("/api/v1/video/jobs", json={"prompt": "cat"}).status_code == 401
    auth = {"Authorization": "Bearer video-auth-fixture"}
    assert client.get("/api/v1/video", headers=auth).status_code == 200
    assert (
        client.post(
            "/api/v1/video/jobs",
            headers={**auth, "Origin": "https://evil.example"},
            json={"prompt": "cat"},
        ).status_code
        == 403
    )


def test_worker_sigkill_reaps_backend_and_releases_slot(video_client, tmp_path, monkeypatch):
    client, runtime = video_client
    _fake_backend(video_client, tmp_path, monkeypatch, sleeping=True)
    record = client.post("/api/v1/video/jobs", json={"prompt": "owned slow backend"}).json()
    directory = runtime.job_dir(record["id"])
    deadline = time.monotonic() + 10
    while not (directory / "backend.pid").exists():
        if time.monotonic() > deadline:
            pytest.fail("backend never started")
        time.sleep(0.05)
    owned_pid = int((directory / "backend.pid").read_text())
    worker_pid = runtime.job(record["id"])["worker_pid"]
    os.kill(worker_pid, signal.SIGKILL)
    assert _terminal(runtime, record["id"])["status"] == "interrupted"
    with pytest.raises(ProcessLookupError):
        os.kill(owned_pid, 0)
    assert "stopping owned backend" in (directory / "generation.log").read_text()
    with file_lock(runtime.root / "execution.lock", blocking=False):
        pass


def test_guardian_timeout_terminates_backend(video_client, tmp_path, monkeypatch):
    from llm_loop.video.worker import run_process

    _, runtime = video_client
    _fake_backend(video_client, tmp_path, monkeypatch, sleeping=True)
    directory = tmp_path / "timeout"
    directory.mkdir()
    argv = [runtime.sd_cli, "--output", str(directory / "raw.webm")]
    with (
        file_lock(runtime.root / "execution.lock") as lock_fd,
        (directory / "log").open("ab") as log,
        pytest.raises(TimeoutError),
    ):
        run_process(argv, directory, log, time.monotonic() + 0.5, lock_fd)
    owned_pid = int((directory / "backend.pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(owned_pid, 0)
