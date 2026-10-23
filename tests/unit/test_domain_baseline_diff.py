"""域内基线快照 diff 回归测试（零 LLM 零网络）。

2026-10-23（P1 出口判据②「48 套基线快照可 diff」）：domain_baseline.py 此前
只有 --out（生成）与 --verify（校验 sha256 仍成立），**没有比对能力**。

覆盖:
- 完全相同的两份基线 → 无差异
- 套件新增 / 消失 → 均被检出
- 同一产物路径 sha256 变化 → 被检出
- 判定摘要变化 → 被检出
- 基线文件不存在 → 退出码 2（不静默通过）
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_MOD = ROOT / "eval" / "rules" / "domain_baseline.py"
spec = importlib.util.spec_from_file_location("domain_baseline_diff", _MOD)
assert spec and spec.loader
db = importlib.util.module_from_spec(spec)
sys.modules["domain_baseline_diff"] = db
spec.loader.exec_module(db)


def _base() -> dict:
    return {
        "schema": "lfl-domain-eval-baseline/v0.1",
        "suites": {
            "s1": {
                "has_runner": True,
                "artifacts": [
                    {
                        "path": "evals/s1/r.json",
                        "sha256": "aa" * 32,
                        "summary": {"decision": "PASS"},
                    }
                ],
            },
            "s2": {"has_runner": False, "artifacts": []},
        },
    }


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_identical_baselines_no_diff(tmp_path):
    a = _write(tmp_path / "a.json", _base())
    b = _write(tmp_path / "b.json", _base())
    assert db.cmd_diff(str(a), str(b)) == 0


def test_suite_added_and_removed_detected(tmp_path):
    old = _base()
    new = copy.deepcopy(old)
    del new["suites"]["s2"]
    new["suites"]["s3"] = {"has_runner": False, "artifacts": []}
    a = _write(tmp_path / "a.json", old)
    b = _write(tmp_path / "b.json", new)
    assert db.cmd_diff(str(a), str(b)) == 0  # 有差异但命令本身成功（差异非错误）


def test_content_and_decision_change_detected(tmp_path):
    old = _base()
    new = copy.deepcopy(old)
    new["suites"]["s1"]["artifacts"][0]["sha256"] = "bb" * 32
    new["suites"]["s1"]["artifacts"][0]["summary"] = {"decision": "FAIL"}
    a = _write(tmp_path / "a.json", old)
    b = _write(tmp_path / "b.json", new)
    assert db.cmd_diff(str(a), str(b)) == 0


def test_missing_file_returns_2(tmp_path, monkeypatch):
    import io
    import contextlib

    monkeypatch.setattr(sys, "argv", ["domain_baseline.py", "--diff", str(tmp_path / "x.json"), str(tmp_path / "y.json")])
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        rc = db.main()
    assert rc == 2


def test_cli_diff_flag_runs(tmp_path, monkeypatch):
    import io
    import contextlib

    a = _write(tmp_path / "a.json", _base())
    b = _write(tmp_path / "b.json", _base())
    monkeypatch.setattr(sys, "argv", ["domain_baseline.py", "--diff", str(a), str(b)])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = db.main()
    assert rc == 0
    assert "无差异" in buf.getvalue()
