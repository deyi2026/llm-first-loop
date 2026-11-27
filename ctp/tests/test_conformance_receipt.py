"""B7 回执：哈希稳定、simulated 恒真、三值判定、落盘往返、协议小件。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctp_conformance.receipt import (
    FAIL,
    INDETERMINATE,
    NOT_CONFIGURED,
    PASS,
    SIMULATED_NOTE,
    Receipt,
    error_code,
    reader_identity,
    sample_set_sha256,
)


def _receipt(**overrides) -> Receipt:
    fields = dict(suite="V7", simulated=True, sample_set_sha256="ab" * 32)
    fields.update(overrides)
    return Receipt(**fields)


def test_sample_set_hash_is_deterministic_and_sensitive():
    base = [{"sample_id": "a", "fault_type": "occlusion", "image_sha256": "00" * 32}]
    assert sample_set_sha256(base) == sample_set_sha256(json.loads(json.dumps(base)))
    assert sample_set_sha256(base) != sample_set_sha256(base + [dict(base[0], sample_id="b")])
    flipped = [dict(base[0], image_sha256="01" * 32)]
    assert sample_set_sha256(base) != sample_set_sha256(flipped)
    with pytest.raises(ValueError):
        sample_set_sha256("not a list")  # type: ignore[arg-type]


def test_receipt_refuses_non_simulated():
    """应拦输入：v0 只有合成数据，禁止生成一份'非 simulated'的回执。"""
    with pytest.raises(ValueError):
        _receipt(simulated=False)


def test_notes_carry_the_simulated_disclaimer():
    assert SIMULATED_NOTE in _receipt().notes


def test_verdict_precedence():
    assert _receipt().finalize().verdict == PASS
    pending = _receipt(not_exercisable=[{"fault_type": "copied_tag", "reason": "M-2b 未实现"}])
    assert pending.finalize().verdict == INDETERMINATE
    unconfigured = _receipt(thresholds_used={"miss_rate_limit ([TBD-V4c])": NOT_CONFIGURED})
    assert unconfigured.finalize().verdict == INDETERMINATE
    tbd_text = _receipt(thresholds_used={"x": "[TBD-V4c]"})
    assert tbd_text.finalize().verdict == INDETERMINATE
    failing = _receipt(
        failures=[{"violation": "misread"}],
        not_exercisable=[{"fault_type": "copied_tag"}],
    )
    assert failing.finalize().verdict == FAIL  # 硬断言失败优先于"无法演练"


def test_write_roundtrip(tmp_path: Path):
    receipt = _receipt(counts={"total": 3}, thresholds_used={"k": 1}).finalize()
    path = receipt.write(tmp_path / "out" / "v7.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == receipt.to_dict()
    for key in ("suite", "simulated", "sample_set_sha256", "verdict", "failures", "counts"):
        assert key in loaded
    assert loaded["verdict"] == PASS


def test_error_code_protocol():
    class Typed(Exception):
        code = "unknown_version"

    class EmptyCode(Exception):
        code = ""

    assert error_code(Typed()) == "unknown_version"
    assert error_code(EmptyCode()) is None
    assert error_code(RuntimeError("no code")) is None
    assert error_code(OSError("x")) is None


def test_reader_identity_is_recorded_or_marked_unknown():
    class Reader:
        reader_id = "r1"
        reader_version = "0.1.0"

    assert reader_identity(Reader()) == {"reader_id": "r1", "reader_version": "0.1.0"}
    assert reader_identity(object()) == {"reader_id": "unknown", "reader_version": "unknown"}
