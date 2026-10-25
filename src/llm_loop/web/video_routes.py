"""Authenticated video management, under the existing auth/Origin middleware."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from llm_loop.video.runtime import (
    VideoConfig,
    VideoError,
    VideoRequest,
    VideoRuntime,
)

router = APIRouter()


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: str
    config: VideoConfig


def runtime(request: Request) -> VideoRuntime:
    settings = request.app.state.engine.settings
    return VideoRuntime(
        settings.data_dir,
        model_root=settings.video_model_root,
        sd_cli=settings.video_sd_cli,
    )


@router.get("/api/v1/video")
def status(request: Request) -> JSONResponse:
    try:
        return JSONResponse(runtime(request).status())
    except VideoError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@router.put("/api/v1/video/config")
def configure(request: Request, body: ConfigUpdate) -> JSONResponse:
    try:
        return JSONResponse(runtime(request).save_config(body.config, body.expected_version))
    except VideoError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@router.post("/api/v1/video/references")
def upload_reference(request: Request, file: Annotated[UploadFile, File()]) -> JSONResponse:
    raw = file.file.read(20 * 1024 * 1024 + 1)
    try:
        return JSONResponse(runtime(request).store_reference(raw), status_code=201)
    except VideoError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@router.get("/api/v1/video/references/{ref}/source", response_model=None)
def reference_source(request: Request, ref: str) -> FileResponse | JSONResponse:
    try:
        path, media_type = runtime(request).reference_original(ref)
        return FileResponse(
            path, media_type=media_type, headers={"Cache-Control": "private, no-store"}
        )
    except VideoError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@router.post("/api/v1/video/jobs")
def generate(request: Request, body: VideoRequest) -> JSONResponse:
    try:
        return JSONResponse(runtime(request).start(body), status_code=202)
    except VideoError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@router.get("/api/v1/video/jobs/{job_id}")
def job(request: Request, job_id: str) -> JSONResponse:
    try:
        return JSONResponse(runtime(request).job(job_id))
    except VideoError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@router.post("/api/v1/video/jobs/{job_id}/cancel")
def cancel(request: Request, job_id: str) -> JSONResponse:
    try:
        return JSONResponse(runtime(request).cancel(job_id), status_code=202)
    except VideoError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@router.get("/api/v1/video/jobs/{job_id}/files/{kind}", response_model=None)
def get_file(request: Request, job_id: str, kind: str) -> FileResponse | JSONResponse:
    try:
        path: Path = runtime(request).file_path(job_id, kind)
        return FileResponse(
            path,
            media_type="video/mp4" if kind == "output" else "text/plain",
            headers={"Cache-Control": "private, no-store"},
        )
    except VideoError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)
