"""P0-E4 S4-a/b: 测试环境自证（收集前预检 + 环境指纹）的单元测试.

预检逻辑全部为 tests/conftest.py 的模块级函数（find_spec 探测不真实 import、
无写副作用）；本文件复用 pytest 已加载的 conftest 模块直测之。模拟"缺依赖/
非 venv"一律 monkeypatch 例外表/依赖清单/环境变量，绝不真实卸载依赖。
"""

from __future__ import annotations

import importlib.util
import re as _re
import sys
from pathlib import Path

import pytest

CONFTEST_PATH = Path(__file__).resolve().parent.parent / "conftest.py"


def _conftest_module():
    """取 pytest 已加载的 tests/conftest 模块（importlib 模式下按 __file__ 匹配）."""
    for mod in list(sys.modules.values()):
        mod_file = getattr(mod, "__file__", None)
        if (
            mod_file
            and Path(mod_file).resolve() == CONFTEST_PATH
            and hasattr(mod, "_run_env_preflight")
        ):
            return mod
    # 兜底: 独立按路径加载（脱离 pytest 命名时仍可测）
    spec = importlib.util.spec_from_file_location("lfl_conftest_under_test", CONFTEST_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cf():
    return _conftest_module()


# ── S4-a: 基础构件 ──
def test_dist_import_name_mapping_and_normalization(cf):
    assert cf._dist_import_name("pycryptodome") == "Crypto"
    assert cf._dist_import_name("lark-oapi") == "lark_oapi"
    assert cf._dist_import_name("prompt-toolkit") == "prompt_toolkit"
    assert cf._dist_import_name("some-future-pkg") == "some_future_pkg"  # 未登记→下划线归一


def test_required_dist_names_from_real_pyproject(cf):
    names = cf._required_dist_names(cf._PROJECT_ROOT / "pyproject.toml")
    assert {"lark-oapi", "pycryptodome", "prompt-toolkit"} <= set(names)
    assert all("==" not in n and ">=" not in n and "<" not in n for n in names)  # 纯 dist 名


def test_find_missing_imports_reports_only_missing(cf, monkeypatch):
    monkeypatch.setattr(
        cf, "_DIST_IMPORT_OVERRIDES", {"lfl-nonexistent-demo": "lfl_nonexistent_demo"}
    )
    missing = cf._find_missing_imports(["lfl-nonexistent-demo", "pytest"])
    assert missing == ["lfl-nonexistent-demo (import lfl_nonexistent_demo)"]


# ── S4-a: 预检主流程 ──
def test_preflight_exit_on_missing_dep_single_diagnostic(cf, monkeypatch):
    """缺依赖 → pytest.exit(10)；单条诊断一次列全缺失 + 双解释器 + reason_code + 修复命令."""
    monkeypatch.setattr(
        cf, "_required_dist_names", lambda _p: ["lfl-missing-b", "lfl-missing-a"]
    )
    with pytest.raises(pytest.exit.Exception) as ei:
        cf._run_env_preflight()
    assert ei.value.returncode == cf._ENV_PREFLIGHT_EXIT_CODE == 10  # 不与测试失败(1)混淆
    msg = ei.value.msg
    assert "reason_code=env_missing_dependency" in msg
    # 一次列全（含排序，不逐个报错）
    assert "lfl-missing-a (import lfl_missing_a)" in msg
    assert "lfl-missing-b (import lfl_missing_b)" in msg
    assert msg.index("lfl-missing-a") < msg.index("lfl-missing-b")
    # 当前解释器路径+版本 / 期望 .venv 解释器+实测版本 / 可直接粘贴修复命令
    assert sys.executable in msg
    assert ".venv/bin/python" in msg
    assert _re.search(r"实测版本 \d+\.\d+", msg)
    assert "python -m pytest" in msg


def test_preflight_skip_valve(cf, monkeypatch):
    """LFL_SKIP_ENV_PREFLIGHT=1 → 跳过预检（即使依赖缺失也不 exit）."""
    monkeypatch.setenv(cf._ENV_PREFLIGHT_SKIP_ENV, "1")
    monkeypatch.setattr(cf, "_required_dist_names", lambda _p: ["lfl-missing-a"])
    assert cf._run_env_preflight() == "skipped"


def test_preflight_ok_in_repo_venv(cf):
    """仓库 .venv 全依赖齐全 → ok（真实环境回归锚点）."""
    assert cf._run_env_preflight() == "ok"


def test_preflight_warn_only_when_deps_ok_but_not_venv(cf, monkeypatch, tmp_path):
    """依赖齐全但 sys.prefix 非仓库 .venv → 仅 PytestWarning，不阻塞（返回 ok）."""
    monkeypatch.setattr(cf, "_required_dist_names", lambda _p: [])  # 依赖齐全
    monkeypatch.setattr(cf, "_PROJECT_ROOT", tmp_path)  # 存在 .venv 但 prefix 不指向它
    (tmp_path / ".venv").mkdir()
    with pytest.warns(pytest.PytestWarning, match="非仓库 .venv"):
        assert cf._run_env_preflight() == "ok"


# ── S4-b: 环境指纹 ──
class _HeaderConfig:
    """pytest_report_header 最小依赖面: 只消费 config.stash（普通 dict 即兼容）."""


def _header_text(cf, status):
    cfg = _HeaderConfig()
    cfg.stash = {}
    cfg.stash[cf._PREFLIGHT_STATUS_KEY] = status
    return "\n".join(cf.pytest_report_header(cfg))


def test_report_header_annotates_preflight_status_and_interpreter(cf):
    for status in ("ok", "skipped"):
        text = _header_text(cf, status)
        assert f"preflight={status}" in text
        assert sys.executable in text
        assert f"llm_loop source={cf._llm_loop_source()}" in text  # 树来源自证行
    assert "LFL env deps:" in _header_text(cf, "ok")  # 依赖版本摘要
    assert "依赖未校验" in _header_text(cf, "skipped")  # skipped 显式声明


def test_dependency_version_summary_matches_required_deps(cf):
    summary = cf._dependency_version_summary()
    names = cf._required_dist_names(cf._PROJECT_ROOT / "pyproject.toml")
    assert len(summary) == len(names)
    assert all(_re.fullmatch(r"[^=]+==[^=]+", item) for item in summary)


# ── S4-b 增补: llm_loop 模块来源自证（宿主 PYTHONPATH 可能钉住旧 release 快照）──
def test_llm_loop_source_resolves_inside_repo_rootdir(cf, recwarn):
    """真实环境锚点: pytest（pythonpath=["src"] 相对 rootdir）解析到工作树 llm_loop."""
    source = cf._llm_loop_source()
    assert source != "unknown"
    assert Path(source).is_relative_to(cf._PROJECT_ROOT)
    cf._check_llm_loop_source(object())  # object() 无 config 期告警 API → 原生通道兜底
    assert len(recwarn) == 0  # rootdir 内 → 不告警


def test_llm_loop_source_outside_rootdir_warns_not_blocks(cf, monkeypatch, tmp_path):
    """来源不在 rootdir 之下 → 仅 PytestWarning（不阻塞），文案含实际路径与期望 rootdir."""
    other = tmp_path / "other-tree" / "llm_loop"
    monkeypatch.setattr(cf, "_llm_loop_source", lambda: str(other))
    with pytest.warns(pytest.PytestWarning, match="不在当前仓库 rootdir") as caught:
        cf._check_llm_loop_source(object())  # 触发原生 warning 兜底分支
    assert str(other) in str(caught[0].message)  # 实际路径
    assert str(cf._PROJECT_ROOT) in str(caught[0].message)  # 期望 rootdir


def test_env_fingerprint_junit_properties_complete(cf):
    """junit 属性集内容面锁定（传输面=record_testsuite_property 官方通道 + autouse 无错执行）."""
    props = dict(cf._env_fingerprint_properties("ok"))
    assert props["lfl_env_preflight"] == "ok"
    assert props["lfl_env_interpreter"] == sys.executable
    assert props["lfl_env_python"]
    assert props["lfl_env_llm_loop_source"] == cf._llm_loop_source()
    dep_count = len(
        cf._required_dist_names(cf._PROJECT_ROOT / "pyproject.toml")
    )
    assert len([k for k in props if k.startswith("lfl_env_dep.")]) == dep_count
    assert all(isinstance(v, str) for v in props.values())  # junit property 值须为字符串
