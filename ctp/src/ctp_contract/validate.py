"""C-5 契约校验器（fail-closed）。

对外接口::

    collect_errors(obj) -> list[ContractError]   收集全部错误（诊断 / 测试）
    parse_observation(obj) -> Observation        首个错误即抛 ContractError
    load_observation(path) -> Observation        从 JSON 文件读

与 JSON Schema 的分工：`ctp/schema/observation.schema.json` 是规范性产物（可跨语言
实现），本模块是 Python 侧等价实现，另加六条 schema 表达不了的规则族——
R1 四元数模长；R2 协方差对称与非负对角；R3 全零不确定度拒绝；R4 非有限数拒绝
（NaN/Inf 可出现在 Python dict 中，JSON 文本层不可表达）；R5 时间戳日历/偏移
语义（pattern 只查形状）；R6 target_index 拒绝整数值浮点（2020-12 的 integer
接受 42.0）。六条与 schema description 声明的集合一一对应。两者在
fixtures 上的分歧集合由
`ctp/tests/test_schema_parity.py` 固定，不允许静默漂移。
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import (
    COVARIANCE_NOT_SYMMETRIC,
    DEGENERATE_UNCERTAINTY,
    ENUM_ERROR,
    FORMAT_ERROR,
    LINKAGE_ERROR,
    MISSING_FIELD,
    QUATERNION_NOT_UNIT,
    RANGE_ERROR,
    TIMESTAMP_MISSING_TIMEZONE,
    TYPE_ERROR,
    UNKNOWN_FIELD,
    ContractError,
)
from .model import (
    DegradationFlag,
    Observation,
    Pose,
    Quaternion,
    Resolution,
    Uncertainty,
    Vector3,
)

_TOP_REQUIRED = (
    "target_index",
    "logical_id",
    "resolution",
    "pose",
    "uncertainty",
    "degradation_flag",
    "timestamp",
    "reader_id",
    "reader_version",
)
_TOP_OPTIONAL = ("schema_version",)
_SCHEMA_VERSION = "ctp.c5/0.1"
_QUAT_NORM_TOL = 1e-3
_COV_TOL = 1e-9
# 秒必须显式出现（与 schema 的 pattern 同构）；时区偏移在正则里可选，
# 以便"缺偏移"落到 timestamp_missing_timezone 这个更具体的错误码，
# 而不是与格式错误混为一谈（两层在"接受/拒绝"上仍然一致）。
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})?$"
)
# 扩展键与 schema 的 patternProperties 同一字符集：x- 之后必须是 ASCII 字母数字开头
_EXT_KEY_RE = re.compile(r"^x-[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_extension_key(name: Any) -> bool:
    return isinstance(name, str) and _EXT_KEY_RE.match(name) is not None


def _parse_vec3(value: Any, path: str) -> tuple[Vector3 | None, list[ContractError]]:
    errors: list[ContractError] = []
    if not isinstance(value, Mapping):
        return None, [ContractError(TYPE_ERROR, path, f"expected object, got {type(value).__name__}")]
    comps: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        if axis not in value:
            errors.append(ContractError(MISSING_FIELD, f"{path}.{axis}", "component absent"))
        elif not _is_number(value[axis]):
            errors.append(ContractError(TYPE_ERROR, f"{path}.{axis}", "expected finite number"))
        else:
            comps[axis] = float(value[axis])
    for key in sorted(set(value) - {"x", "y", "z"}):
        errors.append(ContractError(UNKNOWN_FIELD, f"{path}.{key}", "not a vector component"))
    if errors:
        return None, errors
    return Vector3(comps["x"], comps["y"], comps["z"]), []


def _parse_quaternion(value: Any, path: str) -> tuple[Quaternion | None, list[ContractError]]:
    errors: list[ContractError] = []
    if not isinstance(value, Mapping):
        return None, [ContractError(TYPE_ERROR, path, f"expected object, got {type(value).__name__}")]
    comps: dict[str, float] = {}
    for axis in ("x", "y", "z", "w"):
        if axis not in value:
            errors.append(ContractError(MISSING_FIELD, f"{path}.{axis}", "component absent"))
        elif not _is_number(value[axis]):
            errors.append(ContractError(TYPE_ERROR, f"{path}.{axis}", "expected finite number"))
        else:
            comps[axis] = float(value[axis])
    for key in sorted(set(value) - {"x", "y", "z", "w"}):
        errors.append(ContractError(UNKNOWN_FIELD, f"{path}.{key}", "not a quaternion component"))
    if errors:
        return None, errors
    quat = Quaternion(comps["x"], comps["y"], comps["z"], comps["w"])
    if abs(quat.norm() - 1.0) > _QUAT_NORM_TOL:
        return None, [
            ContractError(
                QUATERNION_NOT_UNIT,
                path,
                f"|q| = {quat.norm():.9f}, tolerance ±{_QUAT_NORM_TOL}",
            )
        ]
    return quat, []


def _parse_pose(value: Any, path: str = "pose") -> tuple[Pose | None, list[ContractError]]:
    errors: list[ContractError] = []
    if not isinstance(value, Mapping):
        return None, [ContractError(TYPE_ERROR, path, f"expected object, got {type(value).__name__}")]
    for name in ("position_m", "quaternion", "frame_ref"):
        if name not in value:
            errors.append(ContractError(MISSING_FIELD, f"{path}.{name}", "mandatory field absent"))
    for key in sorted(set(value) - {"position_m", "quaternion", "frame_ref"}):
        errors.append(ContractError(UNKNOWN_FIELD, f"{path}.{key}", "not a pose field"))
    position = quaternion = None
    if "position_m" in value:
        position, errs = _parse_vec3(value["position_m"], f"{path}.position_m")
        errors.extend(errs)
    if "quaternion" in value:
        quaternion, errs = _parse_quaternion(value["quaternion"], f"{path}.quaternion")
        errors.extend(errs)
    frame_ref = value.get("frame_ref")
    if "frame_ref" in value and not _non_empty_str(frame_ref):
        errors.append(
            ContractError(TYPE_ERROR, f"{path}.frame_ref", "expected non-empty string")
        )
    if errors or position is None or quaternion is None:
        return None, errors
    return Pose(position, quaternion, str(frame_ref)), []


def _parse_covariance(
    value: Any, path: str
) -> tuple[tuple[tuple[float, ...], ...] | None, list[ContractError]]:
    errors: list[ContractError] = []
    if not isinstance(value, list) or len(value) != 6:
        return None, [ContractError(TYPE_ERROR, path, "expected 6x6 array")]
    rows: list[tuple[float, ...]] = []
    for i, row in enumerate(value):
        if not isinstance(row, list) or len(row) != 6:
            errors.append(ContractError(TYPE_ERROR, f"{path}[{i}]", "expected 6 numbers"))
            continue
        if not all(_is_number(item) for item in row):
            errors.append(ContractError(TYPE_ERROR, f"{path}[{i}]", "expected finite numbers"))
            continue
        rows.append(tuple(float(item) for item in row))
    if errors:
        return None, errors
    for i in range(6):
        for j in range(i + 1, 6):
            a, b = rows[i][j], rows[j][i]
            if abs(a - b) > _COV_TOL * max(1.0, abs(a), abs(b)):
                errors.append(
                    ContractError(
                        COVARIANCE_NOT_SYMMETRIC, f"{path}[{i}][{j}]", f"{a!r} != {b!r}"
                    )
                )
    for i in range(6):
        if rows[i][i] < 0:
            errors.append(ContractError(RANGE_ERROR, f"{path}[{i}][{i}]", "diagonal must be >= 0"))
    if errors:
        return None, errors
    return tuple(rows), []


def _parse_uncertainty(
    value: Any, path: str = "uncertainty"
) -> tuple[Uncertainty | None, list[ContractError]]:
    errors: list[ContractError] = []
    if not isinstance(value, Mapping):
        return None, [ContractError(TYPE_ERROR, path, f"expected object, got {type(value).__name__}")]
    required = ("k", "model", "translation_1sigma_m", "rotation_1sigma_deg")
    allowed = set(required) | {"covariance_6x6"}
    for name in required:
        if name not in value:
            errors.append(ContractError(MISSING_FIELD, f"{path}.{name}", "mandatory field absent"))
    for key in sorted(set(value) - allowed):
        if not _is_extension_key(key):
            errors.append(ContractError(UNKNOWN_FIELD, f"{path}.{key}", "not a C-5 field"))

    k = value.get("k")
    if "k" in value:
        if not _is_number(k):
            errors.append(ContractError(TYPE_ERROR, f"{path}.k", "expected finite number"))
        elif float(k) <= 0.0:
            errors.append(
                ContractError(RANGE_ERROR, f"{path}.k", "coverage factor must be > 0")
            )

    model = value.get("model")
    if "model" in value and not _non_empty_str(model):
        errors.append(ContractError(TYPE_ERROR, f"{path}.model", "expected non-empty string"))

    translation = rotation = None
    if "translation_1sigma_m" in value:
        translation, errs = _parse_vec3(value["translation_1sigma_m"], f"{path}.translation_1sigma_m")
        errors.extend(errs)
    if "rotation_1sigma_deg" in value:
        rotation, errs = _parse_vec3(value["rotation_1sigma_deg"], f"{path}.rotation_1sigma_deg")
        errors.extend(errs)

    for label, vec in (("translation_1sigma_m", translation), ("rotation_1sigma_deg", rotation)):
        if vec is None:
            continue
        for axis, comp in (("x", vec.x), ("y", vec.y), ("z", vec.z)):
            if comp < 0:
                errors.append(
                    ContractError(RANGE_ERROR, f"{path}.{label}.{axis}", "1σ must be >= 0")
                )

    covariance = None
    if "covariance_6x6" in value:
        covariance, errs = _parse_covariance(value["covariance_6x6"], f"{path}.covariance_6x6")
        errors.extend(errs)

    if errors or translation is None or rotation is None:
        return None, errors

    sigmas = (translation.x, translation.y, translation.z, rotation.x, rotation.y, rotation.z)
    if all(sigma == 0.0 for sigma in sigmas):
        return None, [
            ContractError(
                DEGENERATE_UNCERTAINTY,
                path,
                "all 1σ values are zero: a zero-uncertainty claim is not a measurement declaration",
            )
        ]

    extensions = {key: item for key, item in value.items() if _is_extension_key(key)}
    return Uncertainty(float(k), str(model), translation, rotation, covariance, extensions), []


def _check_timestamp(value: Any, path: str = "timestamp") -> list[ContractError]:
    if not isinstance(value, str):
        return [ContractError(TYPE_ERROR, path, f"expected string, got {type(value).__name__}")]
    raw = value
    if not _TIMESTAMP_RE.match(raw):
        return [
            ContractError(
                FORMAT_ERROR,
                path,
                "expected ISO 8601 date-time with seconds and UTC offset",
            )
        ]
    candidate = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return [ContractError(FORMAT_ERROR, path, "expected ISO 8601 date-time")]
    if parsed.tzinfo is None:
        return [
            ContractError(TIMESTAMP_MISSING_TIMEZONE, path, "acquisition time must carry a UTC offset")
        ]
    return []


def collect_errors(obj: Any) -> list[ContractError]:
    """收集全部契约违规；空列表即合规。"""
    errors: list[ContractError] = []
    if not isinstance(obj, Mapping):
        return [ContractError(TYPE_ERROR, "<root>", f"expected object, got {type(obj).__name__}")]

    present = set(obj)
    for name in _TOP_REQUIRED:
        if name not in present:
            errors.append(ContractError(MISSING_FIELD, name, "C-5 mandatory field absent"))
    allowed = set(_TOP_REQUIRED) | set(_TOP_OPTIONAL)
    for name in sorted(present - allowed):
        if not _is_extension_key(name):
            errors.append(ContractError(UNKNOWN_FIELD, str(name), "not a C-5 field and not an x- extension"))

    if "schema_version" in present and obj["schema_version"] != _SCHEMA_VERSION:
        errors.append(ContractError(ENUM_ERROR, "schema_version", f"expected {_SCHEMA_VERSION!r}"))

    if "target_index" in present:
        value = obj["target_index"]
        if not _is_int(value):
            errors.append(ContractError(TYPE_ERROR, "target_index", "expected integer"))
        elif value < 0:
            errors.append(ContractError(RANGE_ERROR, "target_index", "must be >= 0"))

    resolution: Resolution | None = None
    if "resolution" in present:
        resource = obj["resolution"]
        if not isinstance(resource, str):
            errors.append(ContractError(TYPE_ERROR, "resolution", "expected string"))
        else:
            try:
                resolution = Resolution(resource)
            except ValueError:
                errors.append(
                    ContractError(
                        ENUM_ERROR, "resolution", "expected code|resolved|unresolved"
                    )
                )

    degradation: DegradationFlag | None = None
    if "degradation_flag" in present:
        flag = obj["degradation_flag"]
        if not isinstance(flag, str):
            errors.append(ContractError(TYPE_ERROR, "degradation_flag", "expected string"))
        else:
            try:
                degradation = DegradationFlag(flag)
            except ValueError:
                errors.append(
                    ContractError(
                        ENUM_ERROR, "degradation_flag", "expected none|coarse|quarantine"
                    )
                )

    logical_ok = "logical_id" in present
    if "logical_id" in present:
        value = obj["logical_id"]
        if value is not None and not _non_empty_str(value):
            errors.append(ContractError(TYPE_ERROR, "logical_id", "expected non-empty string or null"))
            logical_ok = False
    if logical_ok and resolution is not None:
        if resolution is Resolution.UNRESOLVED and obj["logical_id"] is not None:
            errors.append(
                ContractError(LINKAGE_ERROR, "logical_id", "must be null when resolution=unresolved")
            )
        elif resolution is not Resolution.UNRESOLVED and obj["logical_id"] is None:
            errors.append(
                ContractError(
                    LINKAGE_ERROR,
                    "logical_id",
                    f"must be present when resolution={resolution.value}",
                )
            )

    pose = None
    if "pose" in present:
        pose, errs = _parse_pose(obj["pose"])
        errors.extend(errs)
    uncertainty = None
    if "uncertainty" in present:
        uncertainty, errs = _parse_uncertainty(obj["uncertainty"])
        errors.extend(errs)
    if "timestamp" in present:
        errors.extend(_check_timestamp(obj["timestamp"]))
    for name in ("reader_id", "reader_version"):
        if name in present and not _non_empty_str(obj[name]):
            errors.append(ContractError(TYPE_ERROR, name, "expected non-empty string"))

    return errors


def parse_observation(obj: Any) -> Observation:
    """校验并构造 Observation；不合规即抛首个 ContractError。"""
    errors = collect_errors(obj)
    if errors:
        raise errors[0]

    pose, _ = _parse_pose(obj["pose"])
    uncertainty, _ = _parse_uncertainty(obj["uncertainty"])
    if pose is None or uncertainty is None:
        raise RuntimeError("validator invariant violated: structure passed but parse failed")
    extensions = {key: value for key, value in obj.items() if _is_extension_key(key)}
    return Observation(
        target_index=obj["target_index"],
        logical_id=obj["logical_id"],
        resolution=Resolution(obj["resolution"]),
        pose=pose,
        uncertainty=uncertainty,
        degradation_flag=DegradationFlag(obj["degradation_flag"]),
        timestamp=obj["timestamp"],
        reader_id=obj["reader_id"],
        reader_version=obj["reader_version"],
        schema_version=obj.get("schema_version"),
        extensions=extensions,
    )


def load_observation(path: str | Path) -> Observation:
    with Path(path).open("r", encoding="utf-8") as handle:
        return parse_observation(json.load(handle))
