from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("pilot_run_pilot_status_test", HERE / "run_pilot.py")
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_classify = _mod._classify
_merge_resume_result = _mod._merge_resume_result


def test_resume_merge_keeps_semantics_single_prefixed() -> None:
    rec = {"interrupted": True}
    _merge_resume_result(
        rec,
        {
            "ok_run": False,
            "dur": None,
            "resume_semantics": "unsupported-headless-resume",
            "stdout_tail": "UNSUPPORTED",
        },
    )
    assert rec["resume_ok_run"] is False
    assert rec["resume_dur"] is None
    assert rec["resume_semantics"] == "unsupported-headless-resume"
    assert rec["resume_stdout_tail"] == "UNSUPPORTED"
    assert "resume_resume_semantics" not in rec


def test_cline_headless_resume_is_unsupported_not_infra_fail() -> None:
    rec = {
        "interrupted": True,
        "resume_ok_run": False,
        "resume_semantics": "unsupported-headless-resume",
        "resume_stdout_tail": "UNSUPPORTED(cline 3.0.61 headless resume): not invoked by design",
    }
    assert _classify(rec, False) == "UNSUPPORTED"


def test_double_prefixed_legacy_shape_demonstrates_old_bug() -> None:
    rec = {
        "interrupted": True,
        "resume_ok_run": False,
        "resume_resume_semantics": "unsupported-headless-resume",
        "resume_stdout_tail": "UNSUPPORTED(cline 3.0.61 headless resume): not invoked by design",
    }
    assert _classify(rec, False) == "INFRA_FAIL"


def test_da_resume_semantics_remains_task_level_fact() -> None:
    rec = {
        "interrupted": True,
        "resume_ok_run": True,
        "resume_semantics": "new-session-same-workspace-by-design",
    }
    assert _classify(rec, True) == "PASS"
