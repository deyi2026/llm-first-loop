"""C-5 契约：非法样本必须被拒，且错误码稳定可复核。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctp_contract import ContractError, collect_errors, parse_observation

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "invalid"

EXPECTED_CODES = {
    "i01_missing_target_index": "missing_field",
    "i02_missing_timestamp": "missing_field",
    "i03_target_index_string": "type_error",
    "i04_resolution_unknown": "enum_error",
    "i05_degradation_trailing_space": "enum_error",
    "i06_logical_null_with_code": "linkage_error",
    "i07_logical_set_with_unresolved": "linkage_error",
    "i08_quaternion_not_unit": "quaternion_not_unit",
    "i09_timestamp_no_timezone": "timestamp_missing_timezone",
    "i10_k_zero": "range_error",
    "i11_unknown_field": "unknown_field",
    "i12_covariance_asymmetric": "covariance_not_symmetric",
    "i13_zero_sigma": "degenerate_uncertainty",
    "i14_missing_reader_version": "missing_field",
    "i15_negative_sigma": "range_error",
    "i16_nan_position": "type_error",
    "i17_timestamp_no_seconds": "format_error",
    "i18_k_boolean": "type_error",
    "i19_whitespace_reader_id": "type_error",
    "i20_bad_extension_key": "unknown_field",
    "i21_timestamp_leading_space": "format_error",
    "i22_resolution_array": "type_error",
}


def _load(stem: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{stem}.json").read_text(encoding="utf-8"))


def test_fixture_set_is_not_vacuous():
    assert len(EXPECTED_CODES) >= 8, "计划要求 >=8 非法样本"


def test_no_orphan_fixture():
    on_disk = {path.stem for path in FIXTURE_DIR.glob("*.json")}
    assert on_disk == set(EXPECTED_CODES), "fixtures 与期望表不一致：新增样本必须同时登记错误码"


@pytest.mark.parametrize("stem,code", sorted(EXPECTED_CODES.items()))
def test_invalid_fixture_rejected_with_expected_code(stem: str, code: str) -> None:
    errors = collect_errors(_load(stem))
    assert errors, f"{stem} 被判合规，但它是非法样本"
    codes = {error.code for error in errors}
    assert code in codes, f"{stem}: 期望 {code}，实际 {sorted(codes)}"


@pytest.mark.parametrize("stem", sorted(EXPECTED_CODES))
def test_parse_raises_and_reports_path(stem: str) -> None:
    with pytest.raises(ContractError) as excinfo:
        parse_observation(_load(stem))
    error = excinfo.value
    assert error.path, "错误必须带字段路径，否则无法复核"
    assert error.detail
    assert error.code == EXPECTED_CODES[stem] or EXPECTED_CODES[stem] in error.code


def test_root_must_be_object():
    assert [error.code for error in collect_errors([1, 2, 3])] == ["type_error"]
