"""R2 Runtime Resolver 测试（RUNTIME-SOT-WIRE）。

核心验收（design §5.3 矩阵第 6/7 行）：
  shell 残留 LLM_MODEL 不覆盖 .env；显式 CLI/ALLOW_OVERRIDE 才生效且被记录。
"""

import os
from pathlib import Path

from llm_loop.runtime.resolver import (
    apply_to_environ,
    parse_env_file,
    resolve_effective,
)


def _make_env_file(tmp_path: Path, lines: list[str]) -> Path:
    f = tmp_path / ".env"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


def test_parse_env_file_strips_comments_and_trailing_spaces(tmp_path):
    """与 config.load_env_file 语义对齐：行内注释剥离、尾空格去除、非法键跳过。"""
    f = _make_env_file(
        tmp_path,
        [
            "LLM_MODEL=glm/glm-5.3  # 主力模型",
            "HISTORY_MAX_CHARS=150000  ",
            "# 注释行",
            "非法键=值",
            "WEB_PORT=8902",
        ],
    )
    parsed = parse_env_file(f)
    assert parsed["LLM_MODEL"] == "glm/glm-5.3"
    assert parsed["HISTORY_MAX_CHARS"] == "150000"
    assert parsed["WEB_PORT"] == "8902"
    assert "非法键" not in parsed


def test_summary_mode_launch_default_is_off_without_dotenv(tmp_path):
    """Missing .env must not silently activate semantic archive summarization."""
    ec = resolve_effective("web", env={}, workspace_root=tmp_path)
    assert ec.values["SUMMARY_MODE"] == "off"
    assert ec.sources["SUMMARY_MODE"] == "launch_default"


def test_stale_shell_env_does_not_override_dotenv(tmp_path):
    """矩阵第 6 行：shell 残留 LLM_MODEL 不覆盖 .env。"""
    _make_env_file(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    ec = resolve_effective(
        "web",
        env={"LLM_MODEL": "deepseek/deepseek-v4-flash"},
        workspace_root=tmp_path,
    )
    assert ec.values["LLM_MODEL"] == "glm/glm-5.3"
    assert ec.sources["LLM_MODEL"] == "dotenv"
    assert ec.ignored_shell_env["LLM_MODEL"] == "deepseek/deepseek-v4-flash"


def test_shell_override_needs_explicit_flag(tmp_path):
    """矩阵第 7 行：LFL_ALLOW_RUNTIME_OVERRIDE=1 才构成 override 层且来源可溯。"""
    _make_env_file(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    ec = resolve_effective(
        "web",
        env={"LLM_MODEL": "deepseek/deepseek-v4-flash", "LFL_ALLOW_RUNTIME_OVERRIDE": "1"},
        workspace_root=tmp_path,
    )
    assert ec.values["LLM_MODEL"] == "deepseek/deepseek-v4-flash"
    assert ec.sources["LLM_MODEL"] == "shell_override"
    assert ec.allow_runtime_override is True


def test_cli_override_highest_priority(tmp_path):
    _make_env_file(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    ec = resolve_effective(
        "web",
        cli_overrides={"LLM_MODEL": "minimax/MiniMax-M3"},
        env={"LLM_MODEL": "deepseek/deepseek-v4-flash"},
        workspace_root=tmp_path,
    )
    assert ec.values["LLM_MODEL"] == "minimax/MiniMax-M3"
    assert ec.sources["LLM_MODEL"] == "cli"


def test_secret_keys_env_first(tmp_path):
    """密钥类：shell 环境优先（惯例），.env 兜底，来源标记。"""
    _make_env_file(tmp_path, ["LLM_API_KEY=from-dotenv"])
    ec = resolve_effective("web", env={"LLM_API_KEY": "from-env"}, workspace_root=tmp_path)
    assert ec.values["LLM_API_KEY"] == "from-env"
    assert ec.sources["LLM_API_KEY"] == "secret_env"
    ec2 = resolve_effective("web", env={}, workspace_root=tmp_path)
    assert ec2.values["LLM_API_KEY"] == "from-dotenv"
    assert ec2.sources["LLM_API_KEY"] == "dotenv_secret"


def test_apply_to_environ_sets_and_unsets(tmp_path, monkeypatch):
    """effective 值写入环境；被忽略残留键在 .env 未定义时清除。"""
    _make_env_file(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    monkeypatch.setenv("HISTORY_MAX_CHARS", "999999")  # .env 未定义的 shell 残留
    ec = resolve_effective("web", env=dict(os.environ), workspace_root=tmp_path)
    apply_to_environ(ec)
    assert os.environ["LLM_MODEL"] == "glm/glm-5.3"
    assert "HISTORY_MAX_CHARS" not in os.environ  # 残留被清除


def test_summary_no_secret_leak(tmp_path):
    """to_summary 不泄漏密钥明文（整体序列化检查——修正旧断言笔误：
    str(s.values) 中 s.values 是 dict method 对象，其 str 永不含密钥，
    导致 LLM_API_KEY 明文泄漏未被测试拦截，2026-08-29 实测暴露）。"""
    _make_env_file(tmp_path, ["LLM_API_KEY=sk-secret-12345"])
    ec = resolve_effective("web", env={"LLM_API_KEY": "sk-env-67890"}, workspace_root=tmp_path)
    s = ec.to_summary()
    dumped = str(s)  # 摘要整体序列化后不得出现任何明文密钥
    assert "sk-env-67890" not in dumped
    assert "sk-secret-12345" not in dumped
    assert "<secret:" in dumped  # 脱敏标记存在


def test_launch_dry_run(tmp_path, capsys, monkeypatch):
    """launch --dry-run：打印 effective 摘要，不启动服务。"""
    from llm_loop.runtime.launch import main as launch_main

    _make_env_file(tmp_path, ["LLM_MODEL=glm/glm-5.3"])
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    rc = launch_main(["web", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "glm/glm-5.3" in out
    assert '"service": "web"' in out
