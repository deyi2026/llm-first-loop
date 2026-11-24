"""生成 C-5 契约 fixtures（确定性，可重复执行；改动 fixtures 请改这里而不是手改 JSON）。"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALID_DIR = HERE / "valid"
INVALID_DIR = HERE / "invalid"


def base() -> dict:
    return {
        "target_index": 42,
        "logical_id": "0x2A",
        "resolution": "code",
        "pose": {
            "position_m": {"x": 0.0, "y": 0.0, "z": 1.2},
            "quaternion": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            "frame_ref": "REG-FRAME-0001",
        },
        "uncertainty": {
            "k": 2.0,
            "model": "iso-gum-linear-v0",
            "translation_1sigma_m": {"x": 0.0004, "y": 0.0004, "z": 0.0009},
            "rotation_1sigma_deg": {"x": 0.03, "y": 0.03, "z": 0.06},
        },
        "degradation_flag": "none",
        "timestamp": "2026-11-23T10:00:00.123+08:00",
        "reader_id": "ctp-refreader",
        "reader_version": "0.1.0",
    }


def build_valid() -> dict[str, dict]:
    fixtures: dict[str, dict] = {}

    fixtures["v01_minimal_code"] = base()

    resolved = base()
    resolved.update(
        {
            "resolution": "resolved",
            "logical_id": "ctp://example.org/robot-7/tcp",
            "degradation_flag": "coarse",
            "pose": {
                "position_m": {"x": -1.25, "y": 0.5, "z": 3.5},
                "quaternion": {"x": 0.0, "y": 0.7071067811865476, "z": 0.0, "w": 0.7071067811865476},
                "frame_ref": "REG-FRAME-0002",
            },
        }
    )
    fixtures["v02_resolved_coarse"] = resolved

    unresolved = base()
    unresolved.update({"resolution": "unresolved", "logical_id": None, "target_index": 7})
    fixtures["v03_unresolved_null"] = unresolved

    cov = base()
    rows = [[0.0] * 6 for _ in range(6)]
    # 旋转对角必须是 rad²（与 rotation_1sigma_deg 换算一致）；deg² 是 P0-1 的错误
    diag = [
        0.0004**2,
        0.0004**2,
        0.0009**2,
        math.radians(0.03) ** 2,
        math.radians(0.03) ** 2,
        math.radians(0.06) ** 2,
    ]
    for i, value in enumerate(diag):
        rows[i][i] = value
    rows[0][1] = rows[1][0] = 1e-9
    cov["uncertainty"] = dict(cov["uncertainty"], covariance_6x6=rows)
    fixtures["v04_covariance"] = cov

    ext = base()
    ext["x-vendor.temperature_c"] = 20.5
    ext["uncertainty"] = dict(ext["uncertainty"], **{"x-vendor.propagator": "mc-1e5"})
    fixtures["v05_extension"] = ext

    tiny = base()
    tiny["uncertainty"] = dict(
        tiny["uncertainty"],
        translation_1sigma_m={"x": 1e-9, "y": 1e-9, "z": 1e-9},
        rotation_1sigma_deg={"x": 1e-9, "y": 1e-9, "z": 1e-9},
    )
    fixtures["v06_tiny_sigma"] = tiny

    utc = base()
    utc["timestamp"] = "2026-11-23T02:00:00Z"
    fixtures["v07_timestamp_utc_z"] = utc

    negative = base()
    negative["pose"] = dict(
        negative["pose"], position_m={"x": -1.25, "y": 0.0, "z": 3.5}
    )
    fixtures["v08_negative_position"] = negative

    quarantine = base()
    quarantine.update(
        {
            "resolution": "resolved",
            "logical_id": "ctp://example.org/robot-7/wrist",
            "degradation_flag": "quarantine",
        }
    )
    fixtures["v09_quarantine"] = quarantine

    versioned = base()
    versioned["schema_version"] = "ctp.c5/0.1"
    fixtures["v10_schema_version"] = versioned

    return fixtures


def build_invalid() -> dict[str, dict]:
    fixtures: dict[str, dict] = {}

    missing_target = base()
    del missing_target["target_index"]
    fixtures["i01_missing_target_index"] = missing_target

    missing_ts = base()
    del missing_ts["timestamp"]
    fixtures["i02_missing_timestamp"] = missing_ts

    bad_type = base()
    bad_type["target_index"] = "42"
    fixtures["i03_target_index_string"] = bad_type

    bad_resolution = base()
    bad_resolution["resolution"] = "guessed"
    fixtures["i04_resolution_unknown"] = bad_resolution

    bad_degradation = base()
    bad_degradation["degradation_flag"] = "none "
    fixtures["i05_degradation_trailing_space"] = bad_degradation

    null_with_code = base()
    null_with_code["logical_id"] = None
    fixtures["i06_logical_null_with_code"] = null_with_code

    set_with_unresolved = base()
    set_with_unresolved.update({"resolution": "unresolved"})
    fixtures["i07_logical_set_with_unresolved"] = set_with_unresolved

    bad_quat = base()
    bad_quat["pose"] = dict(bad_quat["pose"], quaternion={"x": 0.0, "y": 0.0, "z": 0.0, "w": 2.0})
    fixtures["i08_quaternion_not_unit"] = bad_quat

    no_tz = base()
    no_tz["timestamp"] = "2026-11-23T10:00:00"
    fixtures["i09_timestamp_no_timezone"] = no_tz

    k_zero = base()
    k_zero["uncertainty"] = dict(k_zero["uncertainty"], k=0.0)
    fixtures["i10_k_zero"] = k_zero

    unknown = base()
    unknown["pose_t"] = 1.0
    fixtures["i11_unknown_field"] = unknown

    asymmetric = copy.deepcopy(base())
    rows = [[0.0] * 6 for _ in range(6)]
    rows[0][1] = 1e-6
    rows[1][0] = 2e-6
    asymmetric["uncertainty"] = dict(asymmetric["uncertainty"], covariance_6x6=rows)
    fixtures["i12_covariance_asymmetric"] = asymmetric

    zero_sigma = base()
    zero_sigma["uncertainty"] = dict(
        zero_sigma["uncertainty"],
        translation_1sigma_m={"x": 0.0, "y": 0.0, "z": 0.0},
        rotation_1sigma_deg={"x": 0.0, "y": 0.0, "z": 0.0},
    )
    fixtures["i13_zero_sigma"] = zero_sigma

    missing_reader = base()
    del missing_reader["reader_version"]
    fixtures["i14_missing_reader_version"] = missing_reader

    negative_sigma = base()
    negative_sigma["uncertainty"] = dict(
        negative_sigma["uncertainty"], translation_1sigma_m={"x": -0.001, "y": 0.0, "z": 0.0}
    )
    fixtures["i15_negative_sigma"] = negative_sigma

    nan_position = base()
    nan_position["pose"] = dict(
        nan_position["pose"], position_m={"x": 0.0, "y": 0.0, "z": float("nan")}
    )
    fixtures["i16_nan_position"] = nan_position

    no_seconds = base()
    no_seconds["timestamp"] = "2026-11-23T10:00+08:00"
    fixtures["i17_timestamp_no_seconds"] = no_seconds

    bool_k = base()
    bool_k["uncertainty"] = dict(bool_k["uncertainty"], k=True)
    fixtures["i18_k_boolean"] = bool_k

    blank_reader = base()
    blank_reader["reader_id"] = "  "
    fixtures["i19_whitespace_reader_id"] = blank_reader

    bad_ext = base()
    bad_ext["x-中文"] = 1
    fixtures["i20_bad_extension_key"] = bad_ext

    padded_ts = base()
    padded_ts["timestamp"] = " 2026-11-23T10:00:00Z"
    fixtures["i21_timestamp_leading_space"] = padded_ts

    list_resolution = base()
    list_resolution["resolution"] = []
    fixtures["i22_resolution_array"] = list_resolution

    # 分歧规则 R5（日历/偏移语义）：pattern 只查形状，fromisoformat 查日历
    calendar_ts = base()
    calendar_ts["timestamp"] = "2026-13-45T25:00:00+08:60"
    fixtures["i23_timestamp_calendar_invalid"] = calendar_ts

    # 分歧规则 R6（整数值浮点）：2020-12 的 integer 接受 42.0，_is_int 拒绝 float
    float_index = base()
    float_index["target_index"] = 42.0
    fixtures["i24_target_index_float"] = float_index

    return fixtures


def write_all(mapping: dict[str, dict], directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.json"):
        stale.unlink()
    for name in sorted(mapping):
        with (directory / f"{name}.json").open("w", encoding="utf-8") as handle:
            json.dump(mapping[name], handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return len(mapping)


if __name__ == "__main__":
    valid_count = write_all(build_valid(), VALID_DIR)
    invalid_count = write_all(build_invalid(), INVALID_DIR)
    print(f"valid={valid_count} invalid={invalid_count}")
