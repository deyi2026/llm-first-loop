"""本地模型运行时（lfrt）管理面：status / models / switch / start / stop / restart。

lfrt 是单机 LaunchAgent 管的本地推理服务（MLX 或 llama.cpp/GGUF 后端，
OpenAI 兼容端点）。本模块把它的能力暴露给 Web 前端：

- 切换到任意本地模型（GGUF 或 MLX）；lfrt v1.2 会在类型与后端不符时
  在**单次重启**内自动完成后端交换（旧进程退出→新后端 bootstrap→健康等待→预热）。
- 切换成功后自动把新模型同步进 provider 注册表：只补缺省字段，
  运维已写过的模型 spec 原样保留；注册表热替换，无需重启 web。

长动作以 job 形式后台执行（76GB GGUF 加载+预热可达数分钟），
前端轮询 /jobs/{id} 拿增量输出。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import llm_loop.web.provider_admin as provider_admin

logger = logging.getLogger(__name__)
router = APIRouter()
UTF8JSONResponse = JSONResponse

_JOB_TIMEOUT_S = 900  # 76GB 模型 mmap 加载 + 三段预热的最坏上限
_MAX_LINES = 300
_MAX_JOBS = 12

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


class LocalRuntimeError(RuntimeError):
    def __init__(self, code: str, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


# ------------------------------------------------------------ lfrt 调用层

def _lfrt_path(engine: Any) -> str:
    """lfrt 脚本位置：settings.lfrt_cli（来自 LFL_LFRT_CLI，.env 注入）或进程环境。"""
    settings = getattr(engine, "settings", None)
    candidates = [
        (getattr(settings, "lfrt_cli", "") or "").strip(),
        (os.environ.get("LFL_LFRT_CLI") or "").strip(),
    ]
    for cand in candidates:
        if cand and os.path.isfile(cand):
            return cand
    raise LocalRuntimeError(
        "local_runtime_unavailable",
        "未配置 lfrt（在 .env 设置 LFL_LFRT_CLI 指向 lfrt 脚本后重启服务）。",
        status_code=503,
    )


def _run_lfrt(engine: Any, argv_tail: list[str], timeout_s: float) -> tuple[int, str]:
    """运行 lfrt 子命令，返回 (rc, 合并后的输出)。"""
    path = _lfrt_path(engine)
    argv = [sys.executable, path, *argv_tail]
    try:
        proc = subprocess.run(
            argv, cwd=os.path.dirname(path), capture_output=True, text=True,
            timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise LocalRuntimeError("local_runtime_timeout",
                                "lfrt %s 超时" % " ".join(argv_tail[:2]))
    except OSError as exc:
        raise LocalRuntimeError("local_runtime_spawn_failed",
                                "无法启动 lfrt：%s" % exc, status_code=500)
    out = "\n".join(x for x in (proc.stdout, proc.stderr) if x).strip()
    return proc.returncode, out


def _lfrt_json(engine: Any, argv_tail: list[str], timeout_s: float) -> dict[str, Any]:
    rc, out = _run_lfrt(engine, argv_tail, timeout_s)
    if rc != 0:
        raise LocalRuntimeError("local_runtime_command_failed",
                                "lfrt %s 失败：%s" % (" ".join(argv_tail), out[-500:]),
                                status_code=502)
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        raise LocalRuntimeError("local_runtime_bad_output",
                                "lfrt 输出不是 JSON。", status_code=502)
    if payload.get("ok") is not True:
        raise LocalRuntimeError("local_runtime_not_ok",
                                "lfrt %s 未成功：%s" % (" ".join(argv_tail),
                                                        json.dumps(payload)[:400]),
                                status_code=502)
    return payload.get("data") or {}


# ------------------------------------------------------------ 状态聚合（纯）

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


def _base_url_port(base_url: str) -> int | None:
    try:
        parsed = urlparse(str(base_url))
        if (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
            return None
        return parsed.port
    except ValueError:
        return None


def _find_provider(engine: Any, port: int) -> dict[str, Any] | None:
    """注册表里 base_url 指向本机该端口的 provider（即 lfrt 背书的入口）。"""
    for spec in provider_admin.snapshot(engine).get("providers", []):
        if _base_url_port(spec.get("base_url", "")) == port:
            return {"id": str(spec.get("id")), "base_url": spec.get("base_url")}
    return None


def build_status(engine: Any, status_data: dict, models_data: dict,
                 stashed_backends: list[str] | None = None) -> dict[str, Any]:
    """status --json + models --json + provider 注册表 → 面板载荷（纯函数）。"""
    cfg = status_data.get("config") or {}
    server = status_data.get("server") or {}
    launchd = status_data.get("launchd") or {}
    proc = status_data.get("process") or {}
    port = cfg.get("port") or 8901
    wire_ids = list(server.get("model_ids") or [])
    provider = _find_provider(engine, int(port))
    models = []
    for entry in models_data.get("models") or []:
        gguf = entry.get("gguf") or {}
        models.append({
            "name": entry.get("name"),
            "size_gb": entry.get("size_gb"),
            "kind": "gguf" if gguf else "mlx",
            "shards": gguf.get("shards"),
            "shards_ok": gguf.get("shards_ok"),
            "mmproj": gguf.get("mmproj"),
            "active": bool(entry.get("active")),
        })
    stash = sorted(stashed_backends or [])
    suggested_ref = None
    if provider and wire_ids:
        suggested_ref = "%s/%s" % (provider["id"], wire_ids[0])
    return {
        "backend": cfg.get("backend") or "mlx",
        "port": int(port),
        "alias": cfg.get("alias") or (wire_ids[0] if wire_ids else None),
        "ctx": cfg.get("ctx"),
        "model_path": cfg.get("model_path"),
        "shards": cfg.get("shards") or None,
        "state": {
            "launchd": launchd.get("state"),
            "pid": proc.get("pid") or launchd.get("pid"),
            "rss_gb": round((proc.get("rss_mb") or 0) / 1024.0, 1),
            "port_listening": server.get("port_listening"),
            "health": server.get("health"),
        },
        "free_gb": (status_data.get("memory") or {}).get("free_gb"),
        "wire_model_ids": wire_ids,
        "provider": provider,
        "suggested_model_ref": suggested_ref,
        "stashed_backends": stash,
        "models": models,
    }


def _stashed_backends(engine: Any) -> list[str]:
    """lfrt 同目录 config.json 里的可用后端存档（只读）。"""
    try:
        cfg_path = os.path.join(os.path.dirname(_lfrt_path(engine)), "config.json")
        with open(cfg_path, "r", encoding="utf-8") as fh:
            return sorted(json.load(fh).get("stashed_backends") or [])
    except (OSError, json.JSONDecodeError):
        return []


def fetch_status(engine: Any) -> dict[str, Any]:
    status_data = _lfrt_json(engine, ["status", "--json"], 30)
    try:
        models_data = _lfrt_json(engine, ["models", "--json"], 60)
    except LocalRuntimeError:
        models_data = {}
    payload = build_status(engine, status_data, models_data,
                           _stashed_backends(engine))
    with _JOBS_LOCK:
        payload["job"] = _job_view(_latest_job_id())
    return payload


# ------------------------------------------------------------ 注册表同步

def _model_defaults(cfg: dict) -> dict[str, Any]:
    return {
        "context": cfg.get("ctx") or 65536,
        "max_tokens": 16000,
        "cost_tier": "free",
        "wire_protocol": "openai",
        "send_tool_choice": True,
        "thinking": True,
        "reasoning": True,
        "reasoning_capable": True,
        # reasoning_control 不设默认：与 cognilocal 既有条目一致，
        # 模板的 thinking 控制由 GGUF chat template 自治。
        "reasoning_replay": "none",
        "temperature": 0.0,
    }


def sync_provider_model(engine: Any) -> dict[str, Any]:
    """切换后把新模型同步进 provider 注册表（缺省字段补齐，已有自定义保留）。"""
    data = _lfrt_json(engine, ["status", "--json"], 30)
    cfg = data.get("config") or {}
    wire_ids = (data.get("server") or {}).get("model_ids") or []
    port = int(cfg.get("port") or 0)
    if not port or not wire_ids:
        return {"registry_synced": False, "reason": "runtime_not_serving"}
    provider = _find_provider(engine, port)
    if not provider:
        return {"registry_synced": False,
                "reason": "no_provider_on_port_%d" % port}
    model_id = wire_ids[0]
    defaults = _model_defaults(cfg)

    def change(payload: dict[str, Any]) -> None:
        spec = dict(payload.get(provider["id"]) or {})
        models = dict(spec.get("models") or {})
        existing = dict(models.get(model_id) or {})
        merged = {**defaults, **existing}  # 运维已写的字段优先
        merged.setdefault("enabled", True)
        models[model_id] = merged
        spec["models"] = models
        payload[provider["id"]] = spec

    last_error: Exception | None = None
    for _ in range(2):  # CAS：版本冲突时取新版本重试一次
        snap = provider_admin.snapshot(engine)
        try:
            provider_admin.mutate(engine, expected_version=snap["config_version"],
                                  change=change)
            return {"registry_synced": True, "provider_id": provider["id"],
                    "model_id": model_id,
                    "model_ref": "%s/%s" % (provider["id"], model_id)}
        except provider_admin.ProviderAdminError as exc:
            last_error = exc
            if exc.status_code != 409:
                raise
    raise last_error  # type: ignore[misc]


# ------------------------------------------------------------ job 执行层

def _job_view(job_id: str | None) -> dict[str, Any] | None:
    if not job_id or job_id not in _JOBS:
        return None
    job = _JOBS[job_id]
    return {
        "id": job["id"],
        "action": job["action"],
        "label": job["label"],
        "status": job["status"],
        "started_at": job["started_at"],
        "duration_s": round(job.get("duration_s") or 0.0, 1),
        "rc": job.get("rc"),
        "output_tail": list(job["lines"])[-8:],
        "result": job.get("result"),
        "error": job.get("error"),
    }


def _latest_job_id() -> str | None:
    return max(_JOBS, key=lambda k: _JOBS[k]["started_at"]) if _JOBS else None


def _prune_jobs() -> None:
    if len(_JOBS) > _MAX_JOBS:
        for key in sorted(_JOBS, key=lambda k: _JOBS[k]["started_at"])[:-_MAX_JOBS]:
            _JOBS.pop(key, None)


def _job_command(action: str, body: Any, engine: Any) -> list[str]:
    """动作 → lfrt argv（前置校验，非法直接拒绝，不产生 job）。"""
    if action == "switch_model":
        if not body.model:
            raise LocalRuntimeError("model_required", "switch_model 需要 model。")
        names = {m.get("name") for m in
                 (_lfrt_json(engine, ["models", "--json"], 60).get("models") or [])}
        if body.model not in names:
            raise LocalRuntimeError("unknown_model",
                                    "本地模型库里没有 %s。" % body.model, status_code=404)
        return ["switch", "--model", body.model, "--yes"]
    if action == "switch_backend":
        if body.backend not in ("llama", "mlx"):
            raise LocalRuntimeError("backend_invalid", "backend 必须是 llama 或 mlx。")
        current = _lfrt_json(engine, ["status", "--json"], 30).get("config", {}).get("backend")
        if body.backend == current:
            raise LocalRuntimeError("backend_noop", "后端已是 %s。" % body.backend)
        return ["switch", "--backend", body.backend, "--yes"]
    if action == "restart":
        return ["restart", "--yes"]
    if action == "stop":
        if not body.confirm:
            raise LocalRuntimeError(
                "confirm_required", "停止本地运行时会中断所有本地推理请求；重发并带 confirm=true。",
                status_code=428)
        return ["stop", "--yes"]
    if action == "start":
        return ["start"]
    raise LocalRuntimeError("action_invalid", "未知动作 %s。" % action)


_ACTION_LABELS = {
    "switch_model": "切换模型",
    "switch_backend": "切换后端",
    "restart": "重启服务",
    "stop": "停止服务",
    "start": "启动服务",
}


def _run_job(engine: Any, job: dict[str, Any], argv_tail: list[str],
             post_hook: Callable[[Any], dict] | None) -> None:
    path = _lfrt_path(engine)
    argv = [sys.executable, path, *argv_tail]
    started = time.time()
    try:
        proc = subprocess.Popen(
            argv, cwd=os.path.dirname(path), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)
    except OSError as exc:
        job.update(status="failed", error="spawn failed: %s" % exc,
                   duration_s=time.time() - started)
        return
    timed_out = False
    try:
        assert proc.stdout is not None
        deadline = time.time() + _JOB_TIMEOUT_S
        for line in proc.stdout:
            job["lines"].append(line.rstrip("\n"))
            if time.time() > deadline:
                proc.kill()
                timed_out = True
                break
        rc = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        timed_out = True
        rc = proc.returncode
    job["duration_s"] = time.time() - started
    if timed_out:
        job.update(status="failed", rc=rc, error="job timeout (>%.0fs)" % _JOB_TIMEOUT_S)
        return
    job["rc"] = rc
    if rc != 0:
        job.update(status="failed", error="lfrt 退出码 %d" % rc)
        return
    if post_hook is not None:
        try:
            job["result"] = {**post_hook(engine)}
        except Exception as exc:  # 同步失败不算切换失败，但要让面板看到
            logger.exception("local-runtime registry sync failed")
            job["result"] = {"registry_synced": False,
                             "registry_sync_error": "%s: %s" % (type(exc).__name__, exc)}
    job["status"] = "done"  # result 就绪后才置 done，避免轮询方读到半成品


def start_job(engine: Any, body: Any) -> dict[str, Any]:
    """校验 + 启动后台 job；同一时刻只允许一个长动作。"""
    action = body.action
    argv_tail = _job_command(action, body, engine)
    with _JOBS_LOCK:
        running = [j for j in _JOBS.values() if j["status"] == "running"]
        if running:
            raise LocalRuntimeError("job_busy",
                                    "已有 %s 在执行（%s）。" %
                                    (running[0]["label"], running[0]["id"]),
                                    status_code=409)
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "action": action,
            "label": _ACTION_LABELS.get(action, action),
            "detail": body.model or body.backend or "",
            "status": "running",
            "started_at": time.time(),
            "duration_s": 0.0,
            "rc": None,
            "lines": deque(maxlen=_MAX_LINES),
            "result": None,
            "error": None,
        }
        _JOBS[job_id] = job
        _prune_jobs()
    hook = sync_provider_model if action in ("switch_model", "switch_backend") else None
    thread = threading.Thread(target=_run_job, args=(engine, job, argv_tail, hook),
                              daemon=True, name="lfl-local-runtime-%s" % job_id)
    thread.start()
    return _job_view(job_id)  # type: ignore[return-value]


# ------------------------------------------------------------ HTTP 层

class LocalRuntimeJobRequest(BaseModel):
    action: str
    model: str | None = None
    backend: str | None = None
    confirm: bool = False


def _engine_from(request: Request) -> Any:
    return request.app.state.engine


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, LocalRuntimeError):
        return UTF8JSONResponse(status_code=exc.status_code,
                                content={"error": exc.code, "detail": exc.detail})
    if isinstance(exc, provider_admin.ProviderAdminError):
        return UTF8JSONResponse(status_code=exc.status_code,
                                content={"error": exc.code, "detail": exc.detail})
    logger.exception("local-runtime unexpected failure")
    return UTF8JSONResponse(
        status_code=500,
        content={"error": "local_runtime_failed",
                 "detail": "本地运行时管理失败：%s" % type(exc).__name__})


@router.get("/api/v1/local-runtime")
def local_runtime_status(request: Request) -> JSONResponse:
    try:
        return UTF8JSONResponse(fetch_status(_engine_from(request)))
    except Exception as exc:
        return _error_response(exc)


@router.post("/api/v1/local-runtime/jobs")
def local_runtime_start_job(request: Request, body: LocalRuntimeJobRequest) -> JSONResponse:
    try:
        job = start_job(_engine_from(request), body)
        return UTF8JSONResponse(status_code=202, content={"job": job})
    except Exception as exc:
        return _error_response(exc)


@router.get("/api/v1/local-runtime/jobs/{job_id}")
def local_runtime_job(request: Request, job_id: str) -> JSONResponse:
    with _JOBS_LOCK:
        view = _job_view(job_id)
    if view is None:
        return UTF8JSONResponse(status_code=404,
                                content={"error": "job_not_found", "detail": "job 不存在。"})
    return UTF8JSONResponse(view)
