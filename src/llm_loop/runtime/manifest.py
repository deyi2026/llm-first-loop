"""Runtime Manifest（RUNTIME-SOT-WIRE R3，design §2.5 P0.5/P0.6）。

每服务启动产生 <data_dir>/runtime/runtime_manifest.json——运行时身份与
配置的唯一可核验指纹：

  - workspace/git/venv/module/pid（身份事实，来自 R1 IdentityReport）
  - effective config 摘要与 config_hash（来自 R2 EffectiveConfig，已脱敏）
  - providers base/override/effective 三 hash（漂移治理：任何人都能区分
    "intentional override" 与 "两个 repo 漂移了"）

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


def providers_hashes(data_dir: str | Path) -> dict[str, str]:
    """P0.6：base/override/effective 三 hash。

    effective = base 与 override 顶层键合并后序列化的 hash（override 覆盖
    base）；无 override 文件时 effective_hash == base_hash（override_hash
    为空串）。解析失败如实置空，不伪造。
    """
    data = Path(data_dir)
    base_p = data / "providers.json"
    over_p = data / "providers.override.json"
    base_hash = _sha256_file(base_p)
    override_hash = _sha256_file(over_p)
    effective_hash = base_hash
    if override_hash:
        try:
            merged: dict = json.loads(base_p.read_text()) if base_p.is_file() else {}
            merged.update(json.loads(over_p.read_text()))
            effective_hash = _sha256_text(
                json.dumps(merged, ensure_ascii=False, sort_keys=True))
        except Exception:
            effective_hash = ""  # override 解析失败：如实置空
    return {
        "providers_base_hash": base_hash,
        "providers_override_hash": override_hash,
        "providers_effective_hash": effective_hash,
    }


def _provider_info(model_ref: str, data_dir: str | Path) -> dict[str, Any]:
    """从 providers.json 提取 provider_id / endpoint_host / model 元信息（宽松）。"""
    info: dict[str, Any] = {
        "provider_id": "", "provider_endpoint_host": "", "model_meta": {},
    }
    pid, _, mname = model_ref.partition("/")
    info["provider_id"] = pid
    try:
        data = json.loads((Path(data_dir) / "providers.json").read_text())
        prov = data.get(pid) or {}
        info["provider_endpoint_host"] = (
            (prov.get("base_url") or "").split("//")[-1].split("/")[0])
        info["model_meta"] = (prov.get("models") or {}).get(mname or model_ref, {})
    except Exception:
        pass  # providers.json 缺失/损坏：字段留空，manifest 仍产出（不阻塞启动）
    return info


def build_manifest(service: str, ec: EffectiveConfig,
                   report: IdentityReport) -> dict:
    """合并身份事实 + 配置指纹 + providers 三 hash（design P0.5 字段清单）。"""
    v = ec.values
    model_ref = v.get("LLM_MODEL", "")
    pinfo = _provider_info(model_ref, report.data_dir)
    meta = pinfo.get("model_meta") or {}
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
        "max_tokens": meta.get("max_tokens", ""),
        "model_context": meta.get("context", ""),
        "data_dir": report.data_dir,
        "config_file": report.config_file,
        "config_sources": ec.sources,
        "config_hash": config_hash(ec),
        "ignored_shell_env": sorted(ec.ignored_shell_env),
        # —— providers 漂移治理（P0.6）——
        **providers_hashes(report.data_dir),
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
