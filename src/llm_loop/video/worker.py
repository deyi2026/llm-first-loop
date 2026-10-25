"""Detached H3 worker; request, diagnostics and terminal state are durable."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import BinaryIO

from .runtime import atomic_json, identifier, python_module_command


def run_process(
    argv: list[str],
    directory: Path,
    log: BinaryIO,
    deadline: float,
    lock_fd: int,
    *,
    output: BinaryIO | None = None,
) -> None:
    if (directory / "cancel").exists():
        raise InterruptedError("用户已取消视频生成。")
    read_fd, write_fd = os.pipe()
    try:
        proc = subprocess.Popen(
            python_module_command(
                "llm_loop.video.guardian",
                str(directory),
                str(read_fd),
                str(deadline),
                json.dumps(argv),
            ),
            stdin=subprocess.DEVNULL,
            stdout=output if output is not None else log,
            stderr=log,
            pass_fds=(read_fd, lock_fd),
            start_new_session=True,
        )
    except BaseException:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
    try:
        rc = proc.wait()
        if (directory / "cancel").exists():
            raise InterruptedError("用户已取消视频生成。")
        if rc == 124:
            raise TimeoutError("视频生成超时；未自动重试。")
        if rc:
            raise RuntimeError(f"视频后端退出码 {rc}，请查看完整日志。")
    finally:
        os.close(write_fd)
        # Closing the lifeline tells the guardian to stop its owned group,
        # including when an exception interrupts the worker.
        if proc.poll() is None:
            proc.wait(timeout=10)


def run(root: Path, job_id: str, lock_fd: int) -> None:
    directory = root / "jobs" / identifier(job_id)
    path = directory / "job.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    execution = json.loads((directory / "execution.json").read_text(encoding="utf-8"))
    record.update(status="running", started_at=time.time(), worker_pid=os.getpid())
    atomic_json(path, record)

    def request_cancel(_signum: int, _frame: object) -> None:
        (directory / "cancel").touch(mode=0o600)

    signal.signal(signal.SIGTERM, request_cancel)
    signal.signal(signal.SIGINT, request_cancel)
    deadline = time.monotonic() + execution["timeout_s"]
    try:
        with (directory / "generation.log").open("ab", buffering=0) as log:
            run_process(execution["command"], directory, log, deadline, lock_fd)
            raw = directory / "raw.webm"
            if not raw.is_file() or not raw.stat().st_size:
                raise RuntimeError("后端返回成功但未生成视频文件。")
            output = directory / "output.mp4"
            run_process(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(raw),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(output),
                ],
                directory,
                log,
                deadline,
                lock_fd,
            )
            with (directory / "probe.json").open("wb") as probe:
                run_process(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "stream=codec_type,width,height:format=duration",
                        "-of",
                        "json",
                        str(output),
                    ],
                    directory,
                    log,
                    deadline,
                    lock_fd,
                    output=probe,
                )
            metadata = json.loads((directory / "probe.json").read_text())
            if {s["codec_type"] for s in metadata["streams"]} != {"video", "audio"}:
                raise RuntimeError("产物缺少视频或原生音频流。")
            if float(metadata.get("format", {}).get("duration", 0)) <= 0:
                raise RuntimeError("产物没有有效播放时长。")
            digest = hashlib.sha256()
            with output.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if (directory / "cancel").exists():
                raise InterruptedError("用户已取消视频生成。")
            record.update(
                status="done",
                output={
                    "sha256": digest.hexdigest(),
                    "size_bytes": output.stat().st_size,
                    "metadata": metadata,
                },
            )
    except InterruptedError as exc:
        record.update(status="cancelled", error=str(exc))
    except Exception as exc:
        traceback.print_exc()
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        record["finished_at"] = time.time()
        atomic_json(path, record)
        os.close(lock_fd)


if __name__ == "__main__":
    run(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]))
