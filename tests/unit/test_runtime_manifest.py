"""R3 Runtime Manifest 测试（RUNTIME-SOT-WIRE）。

核心验收（tasks.md R3 / design P0.5）：
  字段完整（P0.5 清单）/ 绝不记录 API key / config 变化 → hash 变化 /
  providers override 三 hash / write-read roundtrip / launch 端到端落盘。
"""
import json
import os
from pathlib import Path

from llm_loop.runtime.identity import compute_identity
from llm_loop.runtime.manifest import (
    build_manifest,
    config_hash,
    health_identity,
    providers_hashes,
    read_manifest,
    write_manifest,
)
from llm_loop.runtime.resolver import resolve_effective

# design P0.5 字段清单（验收断言用，逐项必须存在）
P05_FIELDS = [
    "workspace_root", "git_head", "python_executable", "llm_loop_module",
    "service", "pid", "model_ref", "provider_id", "provider_endpoint_host",
    "history_budget_chars", "max_input_tokens", "max_tokens",
    "data_dir", "config_sources", "config_hash",
    "providers_base_hash", "providers_local_hash", "providers_override_hash", "providers_effective_hash",
]

_PROVIDERS = {
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
        "max_input_tokens": 184000,
        "max_tokens": 16000,
        "models": {"glm-5.3": {"context": 1000000}},
    }
}


def _mk(tmp_path: Path, env_lines: list[str]) -> Path:
    (tmp_path / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "providers.json").write_text(json.dumps(_PROVIDERS))
    return data


def test_manifest_fields_complete_and_no_api_key(tmp_path, monkeypatch):
    """P0.5 字段清单全覆盖 + 密钥绝不入 manifest。"""
    _mk(tmp_path, ["LLM_MODEL=glm/glm-5.3", "HISTORY_MAX_CHARS=150000"])
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path))
    report = compute_identity()
    ec = resolve_effective("web", env={"LLM_API_KEY": "sk-secret-xyz"},
                           workspace_root=tmp_path)
    m = build_manifest("web", ec, report)
    for f in P05_FIELDS:
        assert f in m, f"缺 P0.5 字段: {f}"
    assert "sk-secret-xyz" not in str(m)  # 密钥明文绝不出现
    assert m["model_ref"] == "glm/glm-5.3"
    assert m["provider_id"] == "glm"
    assert m["provider_endpoint_host"] == "open.bigmodel.cn"
    assert m["history_budget_chars"] == "150000"
    assert m["max_input_tokens"] == 184000
    assert m["max_tokens"] == 16000  # model 缺省时继承 provider 级输出预算


def test_config_hash_changes_on_cli_override(tmp_path, monkeypatch):
    """config reload / override → effective hash 必变（R3 验收判据）。"""
    _mk(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path))
    ec1 = resolve_effective("web", workspace_root=tmp_path)
    ec2 = resolve_effective(
        "web", cli_overrides={"LLM_MODEL": "deepseek/deepseek-v4-flash"},
        workspace_root=tmp_path)
    assert config_hash(ec1) != config_hash(ec2)


def test_providers_hashes_override_semantics(tmp_path, monkeypatch):
    """P0.6：无 override → effective==base；有 override → 三 hash 区分。"""
    _mk(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    data = tmp_path / "data"
    h1 = providers_hashes(data)
    assert h1["providers_override_hash"] == ""
    assert h1["providers_effective_hash"] == h1["providers_base_hash"]
    (data / "providers.override.json").write_text(
        json.dumps({"glm": {"history_budget_chars": 100000}}))
    h2 = providers_hashes(data)
    assert h2["providers_override_hash"]
    assert h2["providers_effective_hash"] != h2["providers_base_hash"]



def test_providers_hashes_local_overlay_is_effective_snapshot(tmp_path):
    """Web local overlay owns the effective registry snapshot without rewriting tracked seed."""
    _mk(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    data = tmp_path / "data"
    local = {
        "local": {
            "base_url": "https://local.example/v1",
            "api_key_env": "",
            "default_model": "m",
            "models": {"m": {"context": 262144}},
        }
    }
    (data / "providers.local.json").write_text(json.dumps(local), encoding="utf-8")
    hashes = providers_hashes(data)
    assert hashes["providers_local_hash"]
    assert hashes["providers_effective_hash"] == hashes["providers_local_hash"]
    assert hashes["providers_effective_hash"] != hashes["providers_base_hash"]

def test_write_read_roundtrip_and_health_identity(tmp_path, monkeypatch):
    """原子写 + 读回一致 + /health 精简 identity 回读。"""
    _mk(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path))
    report = compute_identity()
    ec = resolve_effective("web", workspace_root=tmp_path)
    m = build_manifest("web", ec, report)
    out = write_manifest(m, report.data_dir)
    assert out.is_file()
    assert read_manifest(report.data_dir) == m
    ident = health_identity(report.data_dir)
    assert ident["model"] == "glm/glm-5.3"
    assert ident["provider"] == "glm"
    assert ident["config_hash"] == m["config_hash"]


def test_launch_writes_manifest_end_to_end(tmp_path, monkeypatch, capsys):
    """端到端：launch main() 真实路径（runpy 劫持不真启动）→ manifest 落盘。

    验收：web/feishu 启动后 manifest 存在且字段完整。
    """
    from llm_loop.runtime import launch as launch_mod
    _mk(tmp_path, ["LLM_MODEL=glm/glm-5.3", "LLM_API_KEY=sk-dotenv-key"])
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    called = {}
    monkeypatch.setattr(launch_mod.runpy, "run_module",
                        lambda mod, run_name: called.setdefault("mod", mod))
    saved = dict(os.environ)
    try:
        rc = launch_mod.main(["web"])
    finally:  # apply_to_environ 会写进程环境，测试后恢复
        os.environ.clear()
        os.environ.update(saved)
    assert rc == 0
    assert called["mod"] == "llm_loop.web"
    m = read_manifest(tmp_path / "data")
    assert m is not None, "launch 后 manifest 未落盘"
    assert m["service"] == "web"
    assert m["config_sources"]["LLM_MODEL"] == "dotenv"
    assert "sk-dotenv-key" not in json.dumps(m)
    # stderr 应有 manifest 路径回显
    err = capsys.readouterr().err
    assert "runtime_manifest.json" in err


def test_dry_run_does_not_write_manifest(tmp_path, monkeypatch, capsys):
    """dry-run 只预览不落盘（manifest 属于真实启动事实）。"""
    _mk(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    from llm_loop.runtime import launch as launch_mod
    rc = launch_mod.main(["web", "--dry-run"])
    assert rc == 0
    assert not (tmp_path / "data" / "runtime" / "runtime_manifest.json").exists()
    out = capsys.readouterr().out
    assert "config_hash" in out  # 预览内容含指纹
