"""B4 闸门测试（计划 §4.2 B4）：阈值必填无默认、双向抑制、边界、K7 影子通道、无硬编码门槛。

数字只作测试参数，不进规范层常量。
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
from pathlib import Path

import pytest

from ctp_reader.config import ThresholdConfig
from ctp_reader.errors import CONFIG_INVALID, INVALID_INPUT, ReaderError
from ctp_reader.gate import (
    REASON_BELOW_CORNERS,
    REASON_BELOW_RATIO,
    REASON_OK,
    GateDecision,
    ReadEvidence,
    ReadGate,
)

_SRC = Path(__file__).resolve().parents[1] / "src" / "ctp_reader"


def _config(**overrides) -> ThresholdConfig:
    fields = dict(min_visible_corners=4, min_visible_data_ratio=0.8)
    fields.update(overrides)
    return ThresholdConfig(**fields)


def _write(tmp_path: Path, payload: object, name: str = "thresholds.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── 阈值必填、无默认 ───────────────────────────────────────────────


def test_threshold_fields_have_no_numeric_defaults():
    fields = dataclasses.fields(ThresholdConfig)
    defaults = {f.name: f.default for f in fields}
    assert defaults["min_visible_corners"] is dataclasses.MISSING
    assert defaults["min_visible_data_ratio"] is dataclasses.MISSING
    assert defaults["shadow"] is False
    assert defaults["shadow_band"] is None
    parameters = inspect.signature(ThresholdConfig).parameters
    assert parameters["min_visible_corners"].default is inspect.Parameter.empty
    assert parameters["min_visible_data_ratio"].default is inspect.Parameter.empty


def test_constructing_without_thresholds_fails():
    with pytest.raises(TypeError):
        ThresholdConfig()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "overrides, path",
    [
        (dict(min_visible_corners=0), "min_visible_corners"),
        (dict(min_visible_corners=-1), "min_visible_corners"),
        (dict(min_visible_corners=4.0), "min_visible_corners"),
        (dict(min_visible_corners=True), "min_visible_corners"),
        (dict(min_visible_data_ratio=0.0), "min_visible_data_ratio"),
        (dict(min_visible_data_ratio=1.2), "min_visible_data_ratio"),
        (dict(min_visible_data_ratio=float("nan")), "min_visible_data_ratio"),
        (dict(min_visible_data_ratio="0.8"), "min_visible_data_ratio"),
        (dict(shadow=1), "shadow"),
        (dict(shadow=True), "shadow_band"),
        (dict(shadow=True, shadow_band=0.0), "shadow_band"),
        (dict(shadow=True, shadow_band=-0.1), "shadow_band"),
    ],
)
def test_invalid_threshold_values_are_rejected(overrides, path):
    """应拦输入：越界 / 类型不符 / 影子带宽缺失一律 config_invalid，不做强转。"""
    with pytest.raises(ReaderError) as excinfo:
        _config(**overrides)
    assert excinfo.value.code == CONFIG_INVALID
    assert excinfo.value.path == path


def test_from_file_rejects_missing_unknown_and_malformed(tmp_path: Path):
    """应拦输入：声明式文件的缺键 / 多键 / 非法 JSON / 非对象 / 类型不符。"""
    cases = {
        "missing": {"min_visible_corners": 4},
        "unknown": {"min_visible_corners": 4, "min_visible_data_ratio": 0.8, "extra": 1},
        "wrong_type": {"min_visible_corners": "4", "min_visible_data_ratio": 0.8},
        "ratio_string": {"min_visible_corners": 4, "min_visible_data_ratio": "0.8"},
    }
    for label, payload in cases.items():
        with pytest.raises(ReaderError) as excinfo:
            ThresholdConfig.from_file(_write(tmp_path, payload, f"{label}.json"))
        assert excinfo.value.code == CONFIG_INVALID, label
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ReaderError) as excinfo:
        ThresholdConfig.from_file(broken)
    assert excinfo.value.code == CONFIG_INVALID
    with pytest.raises(ReaderError) as excinfo:
        ThresholdConfig.from_file(tmp_path / "absent.json")
    assert excinfo.value.code == CONFIG_INVALID


def test_from_file_roundtrip(tmp_path: Path):
    path = _write(tmp_path, {"min_visible_corners": 6, "min_visible_data_ratio": 0.9})
    loaded = ThresholdConfig.from_file(path)
    assert loaded.min_visible_corners == 6
    assert loaded.min_visible_data_ratio == pytest.approx(0.9)
    assert loaded.shadow is False


# ── 边界与双向抑制 ─────────────────────────────────────────────────


def test_exactly_at_thresholds_is_allowed():
    """边界：恰等于阈值即允许（≥ 语义，含浮点相等）。"""
    gate = ReadGate(_config())
    decision = gate.evaluate(ReadEvidence(visible_corners=4, visible_data_ratio=0.8))
    assert isinstance(decision, GateDecision)
    assert decision.allowed is True
    assert decision.reason == REASON_OK
    assert gate.suppressed_count == 0


@pytest.mark.parametrize(
    "corners, ratio, reason",
    [
        (3, 1.0, REASON_BELOW_CORNERS),
        (4, 0.79, REASON_BELOW_RATIO),
        (0, 0.0, REASON_BELOW_CORNERS),
    ],
)
def test_below_threshold_is_suppressed_and_counted(corners, ratio, reason):
    """错读侧：低于阈值 → 不允许，并累计 suppressed_count（调用方据此零输出）。"""
    gate = ReadGate(_config())
    for _ in range(2):
        decision = gate.evaluate(ReadEvidence(visible_corners=corners, visible_data_ratio=ratio))
        assert decision.allowed is False
        assert decision.reason == reason
    assert gate.suppressed_count == 2


def test_corners_take_precedence_over_ratio():
    gate = ReadGate(_config())
    decision = gate.evaluate(ReadEvidence(visible_corners=2, visible_data_ratio=0.5))
    assert decision.reason == REASON_BELOW_CORNERS


def test_above_thresholds_is_allowed_never_suppressed():
    """漏检侧：达标样本不得被抑制（"永不输出"的退化实现在这里就会露头）。"""
    gate = ReadGate(_config())
    for _ in range(5):
        assert gate.evaluate(ReadEvidence(visible_corners=4, visible_data_ratio=1.0)).allowed is True
    assert gate.suppressed_count == 0


# ── K7 影子通道 ────────────────────────────────────────────────────


def test_shadow_records_near_threshold_without_changing_allowed():
    config = _config(shadow=True, shadow_band=0.25)
    gate = ReadGate(config)
    # 角点 3 落在 [4·0.75, 4·1.25) = [3, 5)：低于阈值 → 仍必须抑制，但记为近阈候选
    below = gate.evaluate(ReadEvidence(visible_corners=3, visible_data_ratio=1.0))
    assert below.allowed is False
    assert below.shadow_candidate is True
    # 角点 4（恰在阈值）同样属近阈带 → 允许，且不得因影子标记改变判定
    at = gate.evaluate(ReadEvidence(visible_corners=4, visible_data_ratio=1.0))
    assert at.allowed is True
    assert at.shadow_candidate is True
    # 远离阈值：不记
    far = gate.evaluate(ReadEvidence(visible_corners=40, visible_data_ratio=1.0))
    assert far.allowed is True
    assert far.shadow_candidate is False
    assert gate.shadow_count == 2
    assert gate.suppressed_count == 1
    assert gate.shadow_log == [
        {"visible_corners": 3, "visible_data_ratio": 1.0, "reason": REASON_BELOW_CORNERS},
        {"visible_corners": 4, "visible_data_ratio": 1.0, "reason": REASON_OK},
    ]


def test_shadow_band_applies_to_ratio_too():
    gate = ReadGate(_config(shadow=True, shadow_band=0.1))
    # 比例 0.78 落在 [0.72, 0.88)：低于 0.8 → 抑制 + 近阈
    decision = gate.evaluate(ReadEvidence(visible_corners=4, visible_data_ratio=0.78))
    assert decision.allowed is False
    assert decision.shadow_candidate is True


def test_shadow_disabled_leaves_no_shadow_state():
    gate = ReadGate(_config())
    for _ in range(3):
        decision = gate.evaluate(ReadEvidence(visible_corners=3, visible_data_ratio=0.5))
        assert decision.shadow_candidate is False
    assert gate.shadow_count == 0
    assert gate.shadow_log == []


def test_shadow_log_carries_no_identifying_payload():
    """影子日志只含几何证据与原因：不得出现 ID / 观测内容的键。"""
    gate = ReadGate(_config(shadow=True, shadow_band=0.5))
    gate.evaluate(ReadEvidence(visible_corners=4, visible_data_ratio=0.8))
    assert set(gate.shadow_log[0]) == {"visible_corners", "visible_data_ratio", "reason"}


# ── 输入与类型守卫 ─────────────────────────────────────────────────


def test_gate_rejects_invalid_inputs():
    with pytest.raises(ReaderError) as excinfo:
        ReadGate("not a config")  # type: ignore[arg-type]
    assert excinfo.value.code == CONFIG_INVALID
    gate = ReadGate(_config())
    with pytest.raises(ReaderError) as excinfo:
        gate.evaluate("nope")  # type: ignore[arg-type]
    assert excinfo.value.code == INVALID_INPUT
    with pytest.raises(ReaderError) as excinfo:
        gate.evaluate(ReadEvidence(visible_corners=-1, visible_data_ratio=0.9))
    assert excinfo.value.code == INVALID_INPUT
    with pytest.raises(ReaderError) as excinfo:
        gate.evaluate(ReadEvidence(visible_corners=4, visible_data_ratio=1.5))
    assert excinfo.value.code == INVALID_INPUT


# ── 无硬编码门槛 ───────────────────────────────────────────────────


def test_no_module_level_numeric_constants_in_gate_modules():
    """模块层不得有被当作门槛的数值常量：config.py / gate.py 顶层不出现数值赋值。"""
    for name in ("config.py", "gate.py"):
        tree = ast.parse((_SRC / name).read_text(encoding="utf-8"))
        offenders = []
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
                value = node.value
            else:
                continue
            if targets and isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
                offenders.append(targets)
        assert not offenders, f"{name}: 模块层数值常量 {offenders}"


def test_error_codes_are_stable_strings():
    from ctp_reader import errors

    assert errors.UNKNOWN_VERSION == "unknown_version"
    assert errors.BELOW_MIN_READABLE == "below_min_readable"
    assert errors.NO_TAG_FOUND == "no_tag_found"
    assert errors.INVALID_INPUT == "invalid_input"
    assert errors.CONFIG_INVALID == "config_invalid"
    assert str(ReaderError(CONFIG_INVALID, "x", "y")) == "config_invalid @ x: y"
