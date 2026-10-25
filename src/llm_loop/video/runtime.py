"""MiniMax H3 configuration and durable generation jobs (POSIX sd.cpp backend).

An inherited flock owns the single video slot across Web process restarts. The
detached worker records its own terminal state; polling never retries generation.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

_MODEL_DIR = "unsloth/MiniMax-H3-GGUF/"


class VideoError(ValueError):
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.status = status


class VideoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diffusion_model: str = _MODEL_DIR + "minimax_h3_ref2va_pruned-Q4_K.gguf"
    text_encoder: str = _MODEL_DIR + "qwen3vl_32b_minimax_h3-Q4_K_M.gguf"
    video_vae: str = _MODEL_DIR + "vae/minimax_h3_video_vae_fp16.safetensors"
    audio_vae: str = _MODEL_DIR + "vae/minimax_h3_audio_vae_fp32.safetensors"
    text_encoder_cpu: bool = True
    offload_to_cpu: bool = True
    timeout_s: int = Field(default=3600, ge=60, le=86400)


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=16000)
    width: int = Field(default=640, ge=128, le=2048)
    height: int = Field(default=384, ge=128, le=2048)
    frames: int = Field(default=56, ge=5, le=345)
    steps: int = Field(default=8, ge=1, le=100)
    seed: int = Field(default=-1, ge=-1, le=2147483647)
    references: list[str] = Field(default_factory=list, max_length=9)

    @model_validator(mode="after")
    def validate_shape(self) -> VideoRequest:
        if not self.prompt.strip():
            raise ValueError("请输入视频描述。")
        if self.width % 32 or self.height % 32 or (self.frames - 5) % 17:
            raise ValueError("宽高必须是 32 的倍数；帧数必须是 17k+5，避免后端静默扩展。")
        return self


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as stream:
            os.chmod(tmp, 0o600)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def identifier(value: str) -> str:
    if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise VideoError("视频资源不存在。", 404)
    return value


@contextmanager
def file_lock(path: Path, *, blocking: bool = True) -> Iterator[int]:
    if os.name != "posix":
        raise VideoError("本地 H3 后端目前需要 macOS 或 Linux。", 503)
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+b") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise VideoError("已有视频任务正在运行，请等待或取消该任务。", 409) from exc
        # close() releases our descriptor, but an inherited worker descriptor
        # deliberately keeps ownership. Explicit LOCK_UN here would release both.
        yield stream.fileno()


def python_module_command(module: str, *args: str) -> list[str]:
    """Bind detached helpers to this source tree without modifying process env."""
    return [
        sys.executable,
        "-c",
        "import sys,runpy;sys.path.insert(0,sys.argv.pop(1));"
        "module=sys.argv.pop(1);runpy.run_module(module,run_name='__main__',alter_sys=True)",
        str(Path(__file__).resolve().parents[2]),
        module,
        *args,
    ]


class VideoRuntime:
    def __init__(
        self, data_dir: str | Path, *, model_root: str | Path = "", sd_cli: str = ""
    ):
        self.root = Path(data_dir).expanduser().resolve() / "video"
        self.models = (
            Path(model_root or Path.home() / ".lmstudio/models")
            .expanduser()
            .resolve()
        )
        self.sd_cli = sd_cli or shutil.which("sd-cli") or ""
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def config(self) -> tuple[VideoConfig, str]:
        path = self.root / "config.json"
        if not path.exists():
            return VideoConfig(), "missing"
        raw = path.read_bytes()
        return VideoConfig.model_validate_json(raw), hashlib.sha256(raw).hexdigest()

    def model_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        candidate = (path if path.is_absolute() else self.models / path).resolve()
        if not candidate.is_relative_to(self.models):
            raise VideoError("模型组件必须位于配置的模型目录内。")
        return candidate

    def save_config(self, config: VideoConfig, expected_version: str) -> dict[str, Any]:
        for key in ("diffusion_model", "text_encoder", "video_vae", "audio_vae"):
            self.model_path(getattr(config, key))
        with file_lock(self.root / "config.lock"):
            _, version = self.config()
            if version != expected_version:
                raise VideoError("视频配置已被更新，请刷新后重试。", 409)
            atomic_json(self.root / "config.json", config.model_dump())
        return self.status()

    def status(self) -> dict[str, Any]:
        config, version = self.config()
        cli = self.sd_cli
        missing = []
        if not cli or not Path(cli).is_file() or not os.access(cli, os.X_OK):
            missing.append("sd-cli（设置 LFL_VIDEO_SD_CLI）")
        if os.name != "posix":
            missing.append("macOS / Linux 后端")
        for name, label in (
            ("diffusion_model", "H3 视频权重"),
            ("text_encoder", "H3 专用 Qwen3-VL 编码器"),
            ("video_vae", "视频 VAE"),
            ("audio_vae", "音频 VAE"),
        ):
            if not self.model_path(getattr(config, name)).is_file():
                missing.append(label)
        for binary in ("ffmpeg", "ffprobe"):
            if not shutil.which(binary):
                missing.append(binary)
        jobs_dir = self.root / "jobs"
        records = (
            sorted(jobs_dir.glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if jobs_dir.exists()
            else []
        )[:20]
        jobs = [self.job(p.parent.name) for p in records]
        jobs.sort(key=lambda job: job["created_at"], reverse=True)
        return {
            "model": "MiniMax H3",
            "backend": "stable-diffusion.cpp",
            "config": config.model_dump(),
            "version": version,
            "prerequisites_ready": not missing,
            "missing": missing,
            "jobs": jobs[:20],
        }

    def job_dir(self, job_id: str) -> Path:
        return self.root / "jobs" / identifier(job_id)

    def job(self, job_id: str) -> dict[str, Any]:
        directory = self.job_dir(job_id)
        path = directory / "job.json"
        if not path.is_file():
            raise VideoError("视频任务不存在。", 404)
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["status"] in {"queued", "running"}:
            try:
                with file_lock(self.root / "execution.lock", blocking=False):
                    # Re-read under the slot lock before declaring interruption.
                    record = json.loads(path.read_text(encoding="utf-8"))
                    if record["status"] in {"queued", "running"}:
                        record.update(
                            status="interrupted",
                            error="视频执行进程已退出；任务未自动重试。",
                            finished_at=time.time(),
                        )
                        atomic_json(path, record)
            except VideoError as exc:
                if exc.status != 409:
                    raise
        return record

    def start(self, request: VideoRequest) -> dict[str, Any]:
        status = self.status()
        if status["missing"]:
            raise VideoError("缺少组件：" + "、".join(status["missing"]), 503)
        config, _ = self.config()
        refs = [self.reference_path(ref) for ref in request.references]
        job_id = uuid.uuid4().hex
        directory = self.job_dir(job_id)
        with file_lock(self.root / "execution.lock", blocking=False) as lock_fd:
            directory.mkdir(parents=True, mode=0o700)
            record: dict[str, Any] = {
                "id": job_id,
                "status": "queued",
                "created_at": time.time(),
                "error": None,
                "request": request.model_dump(),
                "config": config.model_dump(),
                "output": None,
            }
            atomic_json(directory / "job.json", record)
            cli = self.sd_cli
            command = build_command(cli, config, request, self.models, directory / "raw.webm", refs)
            atomic_json(
                directory / "execution.json", {"command": command, "timeout_s": config.timeout_s}
            )
            try:
                with (directory / "generation.log").open("ab") as log:
                    proc = subprocess.Popen(
                        python_module_command(
                            "llm_loop.video.worker",
                            str(self.root),
                            job_id,
                            str(lock_fd),
                        ),
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        pass_fds=(lock_fd,),
                        start_new_session=True,
                    )
                threading.Thread(target=proc.wait, daemon=True, name=f"video-reap-{job_id}").start()
            except OSError as exc:
                record.update(
                    status="failed",
                    error=f"无法启动视频任务：{type(exc).__name__}",
                    finished_at=time.time(),
                )
                atomic_json(directory / "job.json", record)
                raise VideoError(record["error"], 500) from exc
        return record

    def cancel(self, job_id: str) -> dict[str, Any]:
        record = self.job(job_id)
        if record["status"] in {"queued", "running"}:
            (self.job_dir(job_id) / "cancel").touch(mode=0o600)
        return record

    def store_reference(self, raw: bytes) -> dict[str, str]:
        """Preserve exact source bytes before making an inference PNG."""
        if len(raw) > 20 * 1024 * 1024:
            raise VideoError("参考图最大 20 MB。", 413)
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if (
                    image.format not in {"PNG", "JPEG", "WEBP"}
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise VideoError("请使用静态 PNG、JPEG 或 WebP 参考图。")
                if image.width * image.height > 16777216:
                    raise VideoError("参考图最多 1600 万像素。")
                image.load()
                directory = self.root / "references"
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                ref = uuid.uuid4().hex
                original = directory / (ref + ".original")
                with original.open("xb") as stream:
                    stream.write(raw)
                original.chmod(0o600)
                with (directory / (ref + ".png")).open("xb") as stream:
                    ImageOps.exif_transpose(image).convert("RGB").save(stream, format="PNG")
                (directory / (ref + ".png")).chmod(0o600)
                facts = {
                    "id": ref,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "media_type": Image.MIME.get(image.format, "application/octet-stream"),
                }
                atomic_json(directory / (ref + ".json"), facts)
            return facts
        except VideoError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise VideoError("请上传有效的参考图片。") from exc

    def reference_original(self, ref: str) -> tuple[Path, str]:
        directory = self.root / "references"
        ref = identifier(ref)
        metadata = directory / (ref + ".json")
        original = directory / (ref + ".original")
        if not metadata.is_file() or not original.is_file():
            raise VideoError("参考图不存在。", 404)
        facts = json.loads(metadata.read_text())
        return original, str(facts["media_type"])

    def reference_path(self, ref: str) -> Path:
        path = self.root / "references" / (identifier(ref) + ".png")
        if not path.is_file():
            raise VideoError("参考图不存在，请重新上传。", 404)
        return path

    def file_path(self, job_id: str, kind: str) -> Path:
        record = self.job(job_id)
        if kind == "output" and record["status"] != "done":
            raise VideoError("视频尚未成功生成。", 409)
        filename = {"output": "output.mp4", "log": "generation.log", "request": "job.json"}.get(
            kind
        )
        if filename is None:
            raise VideoError("视频文件不存在。", 404)
        path = self.job_dir(job_id) / filename
        if not path.is_file():
            raise VideoError("视频文件不存在。", 404)
        return path


def build_command(
    cli: str,
    config: VideoConfig,
    request: VideoRequest,
    model_root: Path,
    output: Path,
    references: list[Path],
) -> list[str]:
    argv = [cli, "--mode", "vid_gen", "--flash-attn", "off,te=on"]
    for flag, name in (
        ("--diffusion-model", "diffusion_model"),
        ("--llm", "text_encoder"),
        ("--vae", "video_vae"),
        ("--audio-vae", "audio_vae"),
    ):
        path = Path(getattr(config, name)).expanduser()
        argv.extend([flag, str((path if path.is_absolute() else model_root / path).resolve())])
    argv.extend(
        [
            "--prompt",
            request.prompt,
            "--width",
            str(request.width),
            "--height",
            str(request.height),
            "--video-frames",
            str(request.frames),
            "--fps",
            "24",
            "--steps",
            str(request.steps),
            "--seed",
            str(request.seed),
            "--cfg-scale",
            "1.0",
            "--output",
            str(output),
        ]
    )
    if config.text_encoder_cpu:
        argv.extend(["--backend", "te=cpu"])
    if config.offload_to_cpu:
        argv.append("--offload-to-cpu")
    for ref in references:
        argv.extend(["--ref-image", str(ref)])
    return argv
