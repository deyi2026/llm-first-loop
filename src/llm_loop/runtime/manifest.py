"""Runtime Manifest（RUNTIME-SOT-WIRE R3，design §2.5 P0.5/P0.6）。

每服务启动产生 <data_dir>/runtime/runtime_manifest.json——运行时身份与
配置的唯一可核验指纹：

  - workspace/git/venv/module/pid（身份事实，来自 R1 IdentityReport）
  - effective config 摘要与 config_hash（来自 R2 EffectiveConfig，已脱敏）
  - providers tracked base / Web local snapshot / env owner / legacy diagnostic / effective hashes
    （漂移治理：区分公开 seed、本机配置与历史 override）

绝不记录 API key：manifest 是落盘文件，密钥脱敏在 resolver.to_summary
源头完成（_mask_secret），本模块不再二次防御性过滤但保持结构不含密钥键。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .identity import IdentityReport
from .resolver import EffectiveConfig


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_hash(ec: EffectiveConfig) -> str:
    """effective 配置指纹（脱敏 values + sources 排序序列化）。

    config reload / override 变化 → hash 必变（R3 验收判据）。
    """
    payload = json.dumps(ec.to_summary(), ensure_ascii=False, sort_keys=True)
    return _sha256_text(payload)


def _manifest_model_providers_raw(ec: EffectiveConfig) -> str:
    """Observe the MODEL_PROVIDERS value the service will actually consume.

    External process environment owns the value.  Before ``runtime.launch`` has
    applied/loaded dotenv, mirror ``load_env_file`` by reading the same env file so
    the launch manifest and the later service manifest describe one source contract.
    """
    raw = str(os.environ.get("MODEL_PROVIDERS", "") or "").strip()
    if raw:
        return raw
    try:
        from .resolver import parse_env_file

        return str(parse_env_file(ec.env_file).get("MODEL_PROVIDERS", "") or "").strip()
    except Exception:
        return ""


def _parse_provider_object(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def providers_hashes(
    data_dir: str | Path, *, model_providers_raw: str | None = None
) -> dict[str, str]:
    """Hash each provider source and identify only the source Registry consumes.

    Runtime priority is ``MODEL_PROVIDERS > providers.local.json > providers.json > L0``.
    ``providers.override.json`` is retained only as historical drift evidence: no
    production Registry consumer reads it, so it must never be labelled effective.
    A malformed higher-priority source yields an unknown/empty effective hash rather
    than falsely attributing a lower-priority file.
    """
    data = Path(data_dir)
    base_p = data / "providers.json"
    local_p = data / "providers.local.json"
    over_p = data / "providers.override.json"
    base_hash = _sha256_file(base_p)
    local_hash = _sha256_file(local_p)
    override_hash = _sha256_file(over_p)
    env_raw = (
        str(os.environ.get("MODEL_PROVIDERS", "") or "").strip()
        if model_providers_raw is None
        else str(model_providers_raw or "").strip()
    )
    env_hash = _sha256_text(env_raw) if env_raw else ""

    if env_raw:
        effective_hash = env_hash if _parse_provider_object(env_raw) is not None else ""
    elif local_p.is_file():
        try:
            local_value = json.loads(local_p.read_text(encoding="utf-8"))
            effective_hash = local_hash if isinstance(local_value, dict) else ""
        except (OSError, json.JSONDecodeError):
            effective_hash = ""
    elif base_p.is_file():
        try:
            base_value = json.loads(base_p.read_text(encoding="utf-8"))
            effective_hash = base_hash if isinstance(base_value, dict) else ""
        except (OSError, json.JSONDecodeError):
            effective_hash = ""
    else:
        effective_hash = ""  # L0 is synthesized runtime state, not a provider-file hash.

    return {
        "providers_base_hash": base_hash,
        "providers_local_hash": local_hash,
        "providers_override_hash": override_hash,
        "providers_env_hash": env_hash,
        "providers_effective_hash": effective_hash,
    }


def _provider_info(
    model_ref: str, data_dir: str | Path, *, model_providers_raw: str = ""
) -> dict[str, Any]:
    """Read provider/model facts from the same effective source as ProviderRegistry."""
    info: dict[str, Any] = {
        "provider_id": "", "provider_endpoint_host": "",
        "provider_meta": {}, "model_meta": {},
    }
    pid, _, mname = model_ref.partition("/")
    info["provider_id"] = pid
    try:
        raw = str(model_providers_raw or "").strip()
        if raw:
            data = _parse_provider_object(raw)
            if data is None:
                return info
        else:
            root = Path(data_dir)
            provider_file = root / "providers.local.json"
            if not provider_file.is_file():
                provider_file = root / "providers.json"
            data = json.loads(provider_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return info
        prov = data.get(pid) or {}
        if not isinstance(prov, dict):
            return info
        info["provider_endpoint_host"] = (
            (prov.get("base_url") or "").split("//")[-1].split("/")[0])
        info["provider_meta"] = prov
        models = prov.get("models") or {}
        info["model_meta"] = (models.get(mname or model_ref, {}) if isinstance(models, dict) else {})
    except Exception:
        pass  # source missing/malformed: leave facts empty rather than invent a lower source.
    return info


def build_manifest(service: str, ec: EffectiveConfig,
                   report: IdentityReport) -> dict:
    """合并身份事实 + 配置指纹 + providers 各来源/effective hashes。"""
    v = ec.values
    model_ref = v.get("LLM_MODEL", "")
    model_providers_raw = _manifest_model_providers_raw(ec)
    pinfo = _provider_info(
        model_ref, report.data_dir, model_providers_raw=model_providers_raw
    )
    provider_meta = pinfo.get("provider_meta") or {}
    meta = pinfo.get("model_meta") or {}
    max_input_tokens = meta.get("max_input_tokens", provider_meta.get("max_input_tokens", ""))
    max_tokens = meta.get("max_tokens", provider_meta.get("max_tokens", v.get("LLM_MAX_TOKENS", "")))
    return {
        # —— 服务与进程 ——
        "service": service,
        "pid": os.getpid(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        # —— 身份事实（R1 IdentityReport）——
        "workspace_root": report.workspace_root,
        "git_head": report.git_head,
        "python_executable": report.python_executable,
        "venv_root": report.venv_root,
        "llm_loop_module": report.llm_loop_module,
        "identity_ok": report.ok,
        "identity_mode": report.mode,
        # —— effective 配置（R2，已脱敏）——
        "model_ref": model_ref,
        "provider_id": pinfo["provider_id"],
        "provider_endpoint_host": pinfo["provider_endpoint_host"],
        "history_budget_chars": v.get("HISTORY_MAX_CHARS", ""),
        "max_input_tokens": max_input_tokens,
        "max_tokens": max_tokens,
        "model_context": meta.get("context", ""),
        "data_dir": report.data_dir,
        "config_file": report.config_file,
        "config_sources": ec.sources,
        "config_hash": config_hash(ec),
        "ignored_shell_env": sorted(ec.ignored_shell_env),
        # —— providers 漂移治理（P0.6）——
        **providers_hashes(report.data_dir, model_providers_raw=model_providers_raw),
    }


def write_manifest(manifest: dict, data_dir: str | Path) -> Path:
    """原子写 <data_dir>/runtime/runtime_manifest.json（tmp + rename）。"""
    rt_dir = Path(data_dir) / "runtime"
    rt_dir.mkdir(parents=True, exist_ok=True)
    out = rt_dir / "runtime_manifest.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(out)
    return out


def read_manifest(data_dir: str | Path) -> dict | None:
    """读 manifest（缺失/损坏返回 None，fail-open 不抛）。"""
    p = Path(data_dir) / "runtime" / "runtime_manifest.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def default_data_dir() -> str:
    """与 identity.compute_identity 同口径（DATA_DIR env → workspace/data）。"""
    import llm_loop as _lfl
    ws = Path(_lfl.__file__).resolve().parents[2]  # __init__.py → llm_loop → src → workspace
    return os.environ.get("DATA_DIR") or str(ws / "data")


def health_identity(data_dir: str | Path | None = None) -> dict:
    """/health 精简 identity（design P0.5：查问题先看 health，不猜 .env）。"""
    m = read_manifest(data_dir or default_data_dir()) or {}
    return {
        "workspace": m.get("workspace_root", ""),
        "git_head": m.get("git_head", ""),
        "service": m.get("service", ""),
        "model": m.get("model_ref", ""),
        "provider": m.get("provider_id", ""),
        "config_hash": m.get("config_hash", ""),
    }


def write_runtime_manifest(service: str, data_dir: str | Path | None = None) -> Path | None:
    """R3 便捷落盘: 身份事实 + 配置指纹 + providers source/effective hashes → runtime_manifest.json.

    （2026-08-30 重写——恢复半改工作区丢失的未提交 API；原"无参 write_manifest()"
    的等价物，显式 service 参数更清晰。）

    fail-open: 任何异常返回 None 不抛——服务启动路径不因 manifest 落盘失败阻断
    （与垫片期的 try/except 语义一致）。返回落盘文件 Path。
    """
    try:
        from llm_loop.runtime.identity import compute_identity
        from llm_loop.runtime.resolver import resolve_effective

        report = compute_identity()
        ec = resolve_effective(service)
        return write_manifest(build_manifest(service, ec, report), data_dir or default_data_dir())
    except Exception:  # noqa: BLE001 — R3 语义: fail-open 不阻断启动
        return None
