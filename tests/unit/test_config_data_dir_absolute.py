"""EVO-20260830 split-brain 修复防回归: data_dir 默认值绝对化.

背景: data_dir 默认 "./data" 相对路径随进程 cwd 漂移——主区服务进程 cwd=镜像目录时
演进建议落镜像 data/audit/，主区 web 审阅页看不到（EVO-20260829-6a78d4bb/06c96021 实例）。
修复后: 默认值 = 基于包位置的绝对路径（代码所在区=数据所在区），不随 cwd 漂移。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_loop.config import Settings, _DEFAULT_DATA_DIR, load_settings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _minimal_overrides() -> dict:
    return {
        "llm_api_key": "test-key",
        "llm_base_url": "http://localhost:1/v1",
        "llm_model": "test/model",
    }


def test_default_data_dir_is_absolute_and_package_anchored():
    """默认 data_dir 必须是绝对路径且锚定在包所在项目根的 data/。"""
    assert os.path.isabs(_DEFAULT_DATA_DIR), f"相对路径会随 cwd 漂移: {_DEFAULT_DATA_DIR}"
    assert Path(_DEFAULT_DATA_DIR) == _PROJECT_ROOT / "data"
    s = Settings(**_minimal_overrides())
    assert Path(s.data_dir).is_absolute()
    assert Path(s.data_dir) == _PROJECT_ROOT / "data"


def test_data_dir_survives_cwd_drift(tmp_path, monkeypatch):
    """cwd 漂移（如服务进程 cwd=另一工作区）下 from_env 的 data_dir 不变。"""
    monkeypatch.delenv("DATA_DIR", raising=False)
    # 必填 env 预置（load_env_file 的 .env 查找随 cwd 变化，chdir 后不依赖文件）
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1/v1")
    monkeypatch.setenv("LLM_MODEL", "test/model")
    before = load_settings().data_dir
    monkeypatch.chdir(tmp_path)  # 模拟进程 cwd 漂移到任意目录
    after = load_settings().data_dir
    assert before == after, f"data_dir 随 cwd 漂移: {before} -> {after}"
    assert Path(after).is_absolute()
    # audit/sessions 等派生目录同样锚定
    s = load_settings()
    assert Path(s.audit_dir) == _PROJECT_ROOT / "data" / "audit"
    assert Path(s.sessions_dir) == _PROJECT_ROOT / "data" / "sessions"


def test_env_data_dir_override_still_wins(tmp_path, monkeypatch):
    """显式 DATA_DIR env 配置优先于包位置默认（兼容既有部署）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1/v1")
    monkeypatch.setenv("LLM_MODEL", "test/model")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "custom"))
    s = load_settings()
    assert Path(s.data_dir) == tmp_path / "custom"


def test_explicit_ctor_data_dir_unchanged(tmp_path):
    """显式构造传参不受默认值影响（既有调用点零回归）。"""
    s = Settings(data_dir=str(tmp_path / "x"), **_minimal_overrides())
    assert Path(s.data_dir) == tmp_path / "x"
