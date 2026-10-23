"""CI 红数对账门禁回归测试（零 LLM 零网络）。

2026-10-23（P1 出口判据③「CI 门：回归套件红数与 known-reds 对账，超出登记项即失败」）：
仓库此前无任何红数对账机制 —— 红数全靠人工比对，known-reds 文档登记的 4 项与实测
3 条红编号与成因均不同（§18.4），没有机器判据能发现「新增了一条红」。

覆盖:
- 实测红 ⊆ 登记基线 → PASS（存量债放行）
- 实测红 ⊄ 登记基线 → FAIL 退出码 1（新增未登记红 = 阻断）
- 登记项已不红 → PASS + 提示清理（过期登记不阻断）
- 参数化用例 id 保留后缀（[param]），不合并不同参数实例
- 登记基线文件缺失 → 退出码 2（配置缺失必须显式失败，不静默放行）
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_MOD_PATH = ROOT / "eval" / "rules" / "red_reconciliation.py"
spec = importlib.util.spec_from_file_location("red_reconciliation", _MOD_PATH)
assert spec and spec.loader
red_reconciliation = importlib.util.module_from_spec(spec)
sys.modules["red_reconciliation"] = red_reconciliation
spec.loader.exec_module(red_reconciliation)


def _junit(path: Path, cases: list[tuple[str, str | None]]) -> Path:
    """构造 junit xml（与 pytest --junitxml 真实产物同构）。

    cases = [(测试 id, failure message or None)]
    真实 pytest junitxml 对 testcase 写 file="tests/a.py"（原始文件路径）+ classname
    （点号化模块名）+ name（函数名[参数化后缀]）。这里三属性齐备，
    以保证解析路径与真实 CI 产物一致。
    """
    body = []
    for tid, msg in cases:
        # tid 形如 "tests/a.py::test_x"（file::name）；允许省略 ::name（则 name 为空）
        fpath, sep, name = tid.partition("::")
        if not sep:
            fpath, name = tid, ""
        cls = fpath[:-3].replace("/", ".") if fpath.endswith(".py") else fpath.replace("/", ".")
        attrs = f'classname="{cls}" name="{name}" file="{fpath}"'
        if msg is None:
            body.append(f"<testcase {attrs}/>")
        else:
            body.append(f'<testcase {attrs}><failure message="{msg}"/></testcase>')
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<testsuites><testsuite name="pytest" errors="0" failures="1" tests="{len(cases)}">'
        + "".join(body)
        + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return path


def _registry(monkeypatch, tmp_path, registered: list[str]) -> None:
    """把对账脚本的登记基线指向临时文件（不改动仓库真实登记文件）."""
    tmp = tmp_path / "registry.json"
    tmp.write_text(
        json.dumps(
            {"registered": [{"id": f"R{i}", "test": t} for i, t in enumerate(registered)]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(red_reconciliation, "REGISTRY", tmp)


def test_all_registered_passes(tmp_path, monkeypatch):
    """实测红全部已登记 → PASS（退出码 0）."""
    reg = ["tests/a.py::test_x", "tests/b.py::test_y"]
    _registry(monkeypatch, tmp_path, reg)
    rep = _junit(
        tmp_path / "r.xml",
        [("tests/a.py::test_x", "boom"), ("tests/b.py::test_y", "boom")],
    )
    rc = red_reconciliation.main(["--report", str(rep)])
    assert rc == 0


def test_unregistered_new_red_blocks(tmp_path, monkeypatch):
    """出现未登记新红 → FAIL（退出码 1）."""
    _registry(monkeypatch, tmp_path, ["tests/a.py::test_x"])
    rep = _junit(
        tmp_path / "r.xml",
        [("tests/a.py::test_x", "boom"), ("tests/c.py::test_new", "boom")],
    )
    rc = red_reconciliation.main(["--report", str(rep)])
    assert rc == 1


def test_stale_registration_alone_does_not_block(tmp_path, monkeypatch):
    """登记项已不红、且无其他红 → PASS（过期登记只提示清理，不阻断）."""
    _registry(monkeypatch, tmp_path, ["tests/a.py::test_x"])
    rep = _junit(tmp_path / "r.xml", [])
    rc = red_reconciliation.main(["--report", str(rep)])
    assert rc == 0


def test_stale_plus_unregistered_red_blocks(tmp_path, monkeypatch):
    """登记红已过期 + 出现未登记新红 → FAIL（新红超出登记项）."""
    _registry(monkeypatch, tmp_path, ["tests/a.py::test_x"])
    rep = _junit(tmp_path / "r.xml", [("tests/b.py::test_y", "boom")])
    rc = red_reconciliation.main(["--report", str(rep)])
    assert rc == 1


def test_registered_red_still_present_passes(tmp_path, monkeypatch):
    """登记红仍在（存量债）→ PASS（本次提交未引入新红）."""
    _registry(monkeypatch, tmp_path, ["tests/a.py::test_x", "tests/b.py::test_y"])
    rep = _junit(tmp_path / "r.xml", [("tests/a.py::test_x", "boom")])
    rc = red_reconciliation.main(["--report", str(rep)])
    assert rc == 0


def test_parametrized_id_kept_distinct(tmp_path, monkeypatch):
    """参数化用例：不同参数实例视为不同红项（不得合并）."""
    _registry(monkeypatch, tmp_path, ["tests/a.py::test_p[case-1]"])
    rep = _junit(
        tmp_path / "r.xml",
        [("tests/a.py::test_p[case-1]", "boom"), ("tests/a.py::test_p[case-2]", "boom")],
    )
    rc = red_reconciliation.main(["--report", str(rep)])
    # case-2 未登记 → 阻断
    assert rc == 1


def test_missing_registry_fails_loudly(tmp_path, monkeypatch):
    """登记基线文件缺失 → 退出码 2（不静默放行）."""
    monkeypatch.setattr(red_reconciliation, "REGISTRY", tmp_path / "nope.json")
    rep = _junit(tmp_path / "r.xml", [("tests/a.py::test_x", "boom")])
    rc = red_reconciliation.main(["--report", str(rep)])
    assert rc == 2


def test_error_node_counted_as_red(tmp_path, monkeypatch):
    """ERROR（fixture/setup 失败）同样计入红项."""
    _registry(monkeypatch, tmp_path, ["tests/a.py::test_x"])
    rep = _junit(tmp_path / "r.xml", [("tests/b.py::test_err", "setup error")])
    rc = red_reconciliation.main(["--report", str(rep)])
    assert rc == 1
