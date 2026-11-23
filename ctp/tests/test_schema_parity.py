"""JSON Schema 与 Python 校验器的一致性：分歧集合必须被显式固定。

schema 是规范性产物（可跨语言实现），validator 是 Python 侧等价实现，另加三条
schema 表达不了的规则。两者分歧不允许静默增长：本测试把"schema 放行、validator
拒绝"的集合钉死为 VALIDATOR_ONLY。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ctp_contract import collect_errors

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "observation.schema.json"
VALID_DIR = Path(__file__).resolve().parent / "fixtures" / "valid"
INVALID_DIR = Path(__file__).resolve().parent / "fixtures" / "invalid"

VALIDATOR_ONLY = {
    "i08_quaternion_not_unit",
    "i12_covariance_asymmetric",
    "i13_zero_sigma",
    "i16_nan_position",
}
# 反向分歧：validator 放行、schema 拒绝。修正时间戳严格性后应为空集。
SCHEMA_ONLY: set[str] = set()


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_schema())


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_is_valid_against_metaschema():
    Draft202012Validator.check_schema(_schema())


@pytest.mark.parametrize("path", sorted(VALID_DIR.glob("*.json")), ids=lambda item: item.stem)
def test_schema_accepts_all_valid_fixtures(path: Path):
    errors = list(_validator().iter_errors(_load(path)))
    assert not errors, [error.message for error in errors]


@pytest.mark.parametrize("path", sorted(INVALID_DIR.glob("*.json")), ids=lambda item: item.stem)
def test_every_invalid_fixture_is_rejected_by_at_least_one_layer(path: Path):
    raw = _load(path)
    schema_rejects = bool(list(_validator().iter_errors(raw)))
    validator_rejects = bool(collect_errors(raw))
    assert schema_rejects or validator_rejects, f"{path.stem} 两层都放行"


def test_schema_misses_exactly_the_declared_validator_only_set():
    missed = {
        path.stem
        for path in sorted(INVALID_DIR.glob("*.json"))
        if not list(_validator().iter_errors(_load(path)))
    }
    assert missed == VALIDATOR_ONLY, (
        "schema 与 validator 的分歧集合漂移："
        f"实际 {sorted(missed)} vs 声明 {sorted(VALIDATOR_ONLY)}"
    )


def test_validator_never_accepts_what_schema_rejects():
    """反向漂移同样不允许：validator 放行的样本，schema 也必须放行。"""
    accepted = {
        path.stem
        for path in sorted(INVALID_DIR.glob("*.json"))
        if not collect_errors(_load(path))
    }
    assert accepted == SCHEMA_ONLY, f"validator 放行了 schema 拒绝的样本：{sorted(accepted)}"
