"""scratch 出仓库 + 跑批期封条 env（2026-10-24，零 LLM 零网络）.

覆盖:
- 默认 scratch 根在**系统临时目录**，不在仓库内（不再写 data/e2e）
- 每轮 scratch 目录默认清理；``--keep-scratch`` 保留；异常路径同样清理
- 跑批期 ``LFL_HELDOUT_SEALED == "1"``，结束后原样恢复（原存在还原 / 原不存在删除）
- report.json / report.md 记 ``heldout_sealed``

手法：``evaluate`` 在 main 层被 mock（只验编排与报告落盘）；封条用例走**真实**
``evaluate(dry=True)`` + 真实 ``run_dry_sample``（只 spy 观察 env），因此
env 的设置/恢复是产品代码路径而非测试自证。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import run_eval  # noqa: E402  — scripts 层模块（sys.path 注入后导入）

_SEAL = "LFL_HELDOUT_SEALED"
_SCENARIO_FILE = _REPO / "tests" / "eval_sets" / "scenarios_v1.json"


def _fake_scenarios() -> dict:
    """取真实评测集第一个场景（只为拿到合法 verdict 名），缩成 1 样本的假套件."""
    real = json.loads(_SCENARIO_FILE.read_text(encoding="utf-8"))
    sc = dict(real["scenarios"][0])
    sc["samples"] = 1
    return {"name": "fake-suite", "version": "v-fake", "scenarios": [sc]}


def _fake_eval_out(sealed: bool) -> dict:
    return {
        "dry": True,
        "heldout_sealed": sealed,
        # 预算块与真实 _resolve_run_budget 同形（render_markdown 逐键读取，缺键即 KeyError）
        "budget": {
            "profile": "product",
            "base": 500,
            "product_default": 500,
            "pins_honored": True,
            "scenario_pins": {},
            "effective_by_scenario": {"s1": 500},
        },
        "results": [
            {
                "id": "s1",
                "name": "S1",
                "verdict": "fake_verdict",
                "samples": 1,
                "passed": 1,
                "truncated": 0,
                "failed": 0,
                "scored": 1,
                "tokens": {"total_in": 0, "total_out": 0, "avg_per_sample": 0},
                "rate": 1.0,
                "rate_scored": 1.0,
                "truncated_rate": 0.0,
                "ci": [0.0, 1.0],
                "ci_scored": [0.0, 1.0],
                "samples_detail": [],
            }
        ],
    }


class _Recorder:
    """main() 编排观测：记录 evaluate 收到的 workdir / 跑批期 env / 是否抛错."""

    def __init__(self) -> None:
        self.workdirs: list[Path] = []
        self.env_during: list[str | None] = []
        self.exc: BaseException | None = None
        self.sealed_flag = True

    @property
    def workdir(self) -> Path:
        assert len(self.workdirs) == 1, f"evaluate 应被调用 1 次，实际 {len(self.workdirs)}"
        return self.workdirs[0]


def _install_fakes(monkeypatch: pytest.MonkeyPatch, rec: _Recorder) -> None:
    def fake_evaluate(scenarios: dict, **kwargs: object) -> dict:
        rec.workdirs.append(Path(kwargs["workdir"]))  # type: ignore[arg-type]
        rec.env_during.append(os.environ.get(_SEAL))
        if rec.exc is not None:
            raise rec.exc
        return _fake_eval_out(rec.sealed_flag)

    monkeypatch.setattr(run_eval, "load_scenarios", lambda _p: _fake_scenarios())
    monkeypatch.setattr(run_eval, "evaluate", fake_evaluate)


def _run_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: list[str]) -> int:
    argv = ["run_eval.py", "--dry", "--output", str(tmp_path / "out"), *extra]
    monkeypatch.setattr(sys, "argv", argv)
    return run_eval.main()


# ── 1. scratch 根不在仓库内 ──────────────────────────────────────────────


def test_scratch_root_defaults_outside_repo() -> None:
    """默认 scratch 根 = <系统临时目录>/lfl-e2e，不再 <repo>/data/e2e."""
    root = run_eval._SCRATCH_ROOT
    assert str(root) == str(Path(tempfile.gettempdir()) / "lfl-e2e")
    assert not str(root.resolve()).startswith(str(_REPO.resolve()) + os.sep)


def test_main_default_workdir_outside_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """main() 实际传给 evaluate 的 workdir 也在仓库外（编排层，不只常量）."""
    e2e = _REPO / "data" / "e2e"
    before = {p.name for p in e2e.glob("eval-*")} if e2e.is_dir() else set()

    rec = _Recorder()
    _install_fakes(monkeypatch, rec)
    assert _run_main(monkeypatch, tmp_path, []) == 0

    wd = rec.workdir
    assert not str(wd.resolve()).startswith(str(_REPO.resolve()) + os.sep)
    assert wd.parent == run_eval._SCRATCH_ROOT
    # 真跑一轮也不在仓库内新增 scratch（此前 414 个 data/e2e/eval-run-* 的来源）
    after = {p.name for p in e2e.glob("eval-*")} if e2e.is_dir() else set()
    assert after == before


# ── 2. 默认清理 / --keep-scratch 保留 / 异常也清理 ───────────────────────


def test_scratch_removed_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--workdir 覆盖生效，且缺省跑完即删本轮目录."""
    root = tmp_path / "scratch"
    rec = _Recorder()
    _install_fakes(monkeypatch, rec)
    assert _run_main(monkeypatch, tmp_path, ["--workdir", str(root)]) == 0

    wd = rec.workdir
    assert wd.parent == root
    assert not wd.exists(), "缺省应删除本轮 scratch"


def test_scratch_kept_with_keep_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--keep-scratch 时目录保留（供事后排障）."""
    root = tmp_path / "scratch"
    rec = _Recorder()
    _install_fakes(monkeypatch, rec)
    assert _run_main(monkeypatch, tmp_path, ["--workdir", str(root), "--keep-scratch"]) == 0

    wd = rec.workdir
    assert wd.is_dir(), "--keep-scratch 应保留本轮 scratch"
    shutil.rmtree(wd, ignore_errors=True)  # 本测试自己收拾


def test_scratch_removed_when_evaluate_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """异常路径（finally）同样清理，且原本异常仍如实冒泡为退出码 2."""
    root = tmp_path / "scratch"
    rec = _Recorder()
    rec.exc = RuntimeError("llm 崩了")
    _install_fakes(monkeypatch, rec)
    assert _run_main(monkeypatch, tmp_path, ["--workdir", str(root)]) == 2

    assert not rec.workdir.exists(), "异常路径也必须清理 scratch"


# ── 3. 跑批期封条 env ───────────────────────────────────────────────────


def _run_real_dry_eval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, seen: list[str | None]) -> dict:
    """真实 evaluate(dry=True)，只在 run_dry_sample 处 spy 观察跑批期 env."""
    real_runner = run_eval.run_dry_sample

    def spy(*args: object, **kwargs: object) -> dict:
        seen.append(os.environ.get(_SEAL))
        return real_runner(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(run_eval, "run_dry_sample", spy)
    return run_eval.evaluate(
        _fake_scenarios(),
        dry=True,
        samples_override=1,
        workdir=tmp_path / "wd",
    )


def test_seal_env_set_during_batch_and_removed_after(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """原本不存在 → 跑批期 "1"，结束后删除."""
    monkeypatch.delenv(_SEAL, raising=False)
    seen: list[str | None] = []
    out = _run_real_dry_eval(monkeypatch, tmp_path, seen)

    assert seen, "run_dry_sample 应至少被调用一次"
    assert set(seen) == {"1"}
    assert _SEAL not in os.environ, "结束后应删除（原本不存在）"
    assert out["heldout_sealed"] is True


def test_seal_env_set_during_batch_and_restored_after(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """原本存在（非 "1"）→ 跑批期 "1"，结束后**还原原值**."""
    monkeypatch.setenv(_SEAL, "legacy")
    seen: list[str | None] = []
    out = _run_real_dry_eval(monkeypatch, tmp_path, seen)

    assert set(seen) == {"1"}
    assert os.environ[_SEAL] == "legacy", "结束后应还原原值"
    assert out["heldout_sealed"] is True


def test_seal_env_restored_when_runner_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """跑批异常 → finally 恢复原状，异常仍冒泡（不吞）."""
    monkeypatch.delenv(_SEAL, raising=False)

    def boom(*args: object, **kwargs: object) -> dict:
        assert os.environ.get(_SEAL) == "1"
        raise RuntimeError("runner 崩了")

    monkeypatch.setattr(run_eval, "run_dry_sample", boom)
    with pytest.raises(RuntimeError, match="runner 崩了"):
        run_eval.evaluate(_fake_scenarios(), dry=True, samples_override=1, workdir=tmp_path / "wd")

    assert _SEAL not in os.environ


# ── 4. 报告记 heldout_sealed ────────────────────────────────────────────


def test_report_records_heldout_sealed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """report.json 有 heldout_sealed 字段，report.md 有人读的一行（事后可核对）."""
    rec = _Recorder()
    rec.sealed_flag = True
    _install_fakes(monkeypatch, rec)
    assert _run_main(monkeypatch, tmp_path, ["--workdir", str(tmp_path / "scratch")]) == 0

    out = tmp_path / "out"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["heldout_sealed"] is True
    assert "heldout_sealed=true" in (out / "report.md").read_text(encoding="utf-8")


def test_end_to_end_main_with_real_evaluate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """整链路过**真实** evaluate(dry)：scratch 出仓库→跑完即删→env 复原→report 记 true."""
    monkeypatch.delenv(_SEAL, raising=False)
    real_runner = run_eval.run_dry_sample
    seen: list[str | None] = []

    def spy(*args: object, **kwargs: object) -> dict:
        seen.append(os.environ.get(_SEAL))
        return real_runner(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(run_eval, "run_dry_sample", spy)
    # 只替换输入（评测集内容），evaluate / 编排 / 落盘全部走产品代码
    monkeypatch.setattr(run_eval, "load_scenarios", lambda _p: _fake_scenarios())
    root = tmp_path / "scratch"
    assert _run_main(monkeypatch, tmp_path, ["--workdir", str(root), "--samples", "1"]) == 0

    assert seen and set(seen) == {"1"}, "跑批期必须处于封条下"
    assert _SEAL not in os.environ, "跑完应复原（原本不存在）"
    assert root.is_dir() and list(root.iterdir()) == [], "本轮 scratch 应已删除"
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["heldout_sealed"] is True


def test_report_records_heldout_sealed_false(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """未在封条下跑时如实记 false（不谎报 true）."""
    rec = _Recorder()
    rec.sealed_flag = False
    _install_fakes(monkeypatch, rec)
    assert _run_main(monkeypatch, tmp_path, ["--workdir", str(tmp_path / "scratch")]) == 0

    out = tmp_path / "out"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["heldout_sealed"] is False
    assert "heldout_sealed=false" in (out / "report.md").read_text(encoding="utf-8")


# ── 5. 场景集 meta（name/version）：held-out 文件有键 + 缺键零崩溃 ──────
#
# 回归背景：evals/heldout/v1/scenarios_heldout_v1.json 顶层曾只有
# note/scenarios/source，烟测 4 样本全部跑完后报告阶段
# scenarios['version'] 直接 KeyError（回执：评测异常: 'version'）。

_HELDOUT_DIR = _REPO / "evals" / "heldout" / "v1"


def test_heldout_scenarios_file_has_name_and_version() -> None:
    """held-out 场景文件顶层必须有 name/version（version 与 manifest 对齐）."""
    d = json.loads((_HELDOUT_DIR / "scenarios_heldout_v1.json").read_text(encoding="utf-8"))
    assert d["name"] == "heldout-v1"
    manifest = json.loads((_HELDOUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert d["version"] == manifest["version"]


def test_report_meta_missing_name_version_zero_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """无 name/version 的最小场景集走真实 main() 报告路径不 KeyError.

    走真实 main()（只 mock evaluate 输入/输出），同时覆盖两处取值现场：
    report.md 头部（render_markdown 的 name/version）与 report.json 的
    scenario_version；缺键时必须落到缺省值，而不是崩溃。
    """
    sc = dict(_fake_scenarios()["scenarios"][0])
    sc["samples"] = 1
    minimal = {"scenarios": [sc]}  # 故意缺顶层 name/version
    monkeypatch.setattr(run_eval, "load_scenarios", lambda _p: minimal)
    monkeypatch.setattr(run_eval, "evaluate", lambda s, **kw: _fake_eval_out(True))

    assert _run_main(monkeypatch, tmp_path, []) == 0

    out = tmp_path / "out"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["scenario_version"] == "unknown"
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "评测集: unnamed" in md
    assert "version unknown" in md
