"""V4 双向降级（SPEC §11.2-V4、§5 C-4）。

判据（逐字见 docs/conformance/V4-degradation.md）：
① 低于 [TBD-V4a] / [TBD-V4b] 的样本误读率 = 0；
② 条件达标样本漏检率 ≤ [TBD-V4c]（N ≥ [TBD-V4d]）；"永不输出"必须判为不通过。
"""

from __future__ import annotations

import math
from typing import Any

from ._runner import KNOWN_INDICES, drive
from .receipt import NOT_CONFIGURED, Receipt, is_limit, reader_identity, sample_set_sha256
from .synth import (
    crop_corners,
    crop_data_column,
    descriptions,
    geometry,
    index_with_dark_data_columns,
    make_sample,
    render_tag,
)


def build_samples(seed: int = 0) -> list[dict]:
    """两组样本，几何真值随样本携带（runner 据此分组，不采信读码器自述）。

    - 裁到边框以内：上+左 / 仅左 / 左+上+右 → 完整角点 1 / 2 / 0（数据区完整；矩形裁剪裁掉的是整条边）；
    - 裁到数据列 → 完整角点 2、数据位可见比例 5/6；
    - 不裁 → 完整角点 4、比例 1.0（达标组候选）。
    """
    samples: list[dict] = []
    index = index_with_dark_data_columns(2)
    for remove in (1, 2, 3):
        samples.append(
            make_sample(
                "cropped",
                f"crop_corners_{remove}",
                "occlusion_corners",
                "suppress_if_below_threshold",
                crop_corners(render_tag(index), remove),
                **geometry(remove),
                target_index=index,
            )
        )
    samples.append(
        make_sample(
            "cropped",
            "crop_data_column",
            "occlusion_data_column",
            "suppress_if_below_threshold",
            crop_data_column(render_tag(index)),
            **geometry(2, data_column_lost=True),
            target_index=index,
        )
    )
    for index in KNOWN_INDICES:
        samples.append(
            make_sample("intact", f"intact_{index:03d}", "none", "read", render_tag(index), **geometry(0))
        )
    return samples


def _split(samples: list[dict], min_corners: int, min_ratio: float) -> tuple[list[dict], list[dict]]:
    below, at_threshold = [], []
    for sample in samples:
        corners = sample["description"]["visible_corners"]
        ratio = sample["description"]["visible_data_ratio"]
        if corners < min_corners or ratio < min_ratio:
            below.append(sample)
        else:
            at_threshold.append(sample)
    return below, at_threshold


def _in_range(value: Any, low: float, high: float | None) -> bool:
    """已配置且可用：有限数值（排除 bool、NaN、±inf），且落在 [low, high] 内。"""
    if not (is_limit(value) and math.isfinite(value)):
        return False
    return value >= low and (high is None or value <= high)


def _required_threshold(config: dict, key: str, *, low: float, high: float | None = None) -> Any:
    """必填分组阈值：缺失或不可用一律拒绝运行——分组做不了就不产出回执。"""
    value = config.get(key)
    if not _in_range(value, low, high):
        raise ValueError(
            f"V4 requires '{key}' to be a finite number in [{low}, {high if high is not None else 'inf'}] "
            f"(pass the same values the reader's gate uses); got {value!r}"
        )
    return value


def _optional_limit(config: dict, key: str, *, low: float, high: float | None, notes: list[str]) -> Any:
    """可选上限：未提供 → 未配置；提供了但不可用 → 同样按未配置处理并留痕。

    不可用的值（None / NaN / bool / 非数值 / ±inf / 越界）绝不能当作"已配置"：
    否则上限检查被跳过，回执会在一个无法使用的上限下判 pass（违反 receipt 的三值判定规则）。
    """
    value = config.get(key, NOT_CONFIGURED)
    if isinstance(value, str) and (value == NOT_CONFIGURED or value.startswith("[TBD-")):
        return value  # 未配置哨兵原样保留：finalize() 据此判 indeterminate
    if not _in_range(value, low, high):
        notes.append(
            f"'{key}' 提供了不可用的值 {value!r}（须为 [{low}, {high if high is not None else 'inf'}] 内的有限数值）："
            "按未配置处理，本轮不足以支撑判定"
        )
        return NOT_CONFIGURED
    return value


def run(
    reader: Any, *, config: dict, samples: list[dict] | None = None, seed: int = 0
) -> dict:
    notes: list[str] = []
    min_corners = _required_threshold(config, "min_visible_corners", low=0)
    min_ratio = _required_threshold(config, "min_visible_data_ratio", low=0, high=1)
    miss_limit = _optional_limit(config, "miss_rate_limit", low=0, high=1, notes=notes)
    min_size = _optional_limit(config, "min_sample_size", low=1, high=None, notes=notes)

    samples = build_samples(seed) if samples is None else samples
    below, at_threshold = _split(samples, min_corners, min_ratio)
    results_by_id = {record["sample_id"]: record for record in drive(reader, samples)}

    counts = {
        "total": len(samples),
        "below_total": len(below),
        "below_misread": 0,
        "below_suppressed_by_gate": 0,
        "below_refused_other": 0,
        "below_silent": 0,
        "at_total": len(at_threshold),
        "at_detected": 0,
        "at_missed_by_gate": 0,
        "at_refused_other": 0,
        "at_silent": 0,
    }
    failures: list[dict] = []
    for sample in below:
        record = results_by_id[sample["description"]["sample_id"]]
        if record["outcome"] == "observation":
            counts["below_misread"] += 1
            failures.append(
                {
                    "sample_id": record["sample_id"],
                    "violation": "misread_below_threshold",
                    "detail": f"output target_index={record.get('target_index')} below minimum readable condition",
                }
            )
        elif record["outcome"] == "refused" and record["code"] == "below_min_readable":
            counts["below_suppressed_by_gate"] += 1
        elif record["outcome"] == "refused":
            counts["below_refused_other"] += 1
        else:
            counts["below_silent"] += 1
    for sample in at_threshold:
        record = results_by_id[sample["description"]["sample_id"]]
        if record["outcome"] == "observation":
            counts["at_detected"] += 1
        elif record["outcome"] == "refused" and record["code"] == "below_min_readable":
            counts["at_missed_by_gate"] += 1
        elif record["outcome"] == "refused":
            counts["at_refused_other"] += 1
        else:
            counts["at_silent"] += 1

    miss_rate = None
    not_exercisable: list[dict] = []
    if counts["at_total"] == 0:
        not_exercisable.append(
            {
                "dimension": "at_threshold_group",
                "reason": "在给定阈值下没有达标样本（合成集最大可见角点为 4、比例为 1.0）",
            }
        )
    else:
        # 漏检 = 达标样本未产生观测（被闸门抑制，或其他拒绝 / 静默）——与读码器拒绝原因无关
        missed = counts["at_total"] - counts["at_detected"]
        miss_rate = missed / counts["at_total"]
        counts["at_missed"] = missed
        if counts["at_detected"] == 0:
            failures.append(
                {
                    "dimension": "at_threshold_group",
                    "violation": "never_outputs",
                    "detail": "达标样本无一输出：'永不输出'必须判为不通过（SPEC §11.2-V4）",
                }
            )
        if is_limit(miss_limit) and miss_rate > miss_limit:
            failures.append(
                {
                    "dimension": "at_threshold_group",
                    "violation": "miss_rate_exceeds_limit",
                    "detail": f"miss_rate={miss_rate:.4f} > {miss_limit}",
                }
            )
        if is_limit(min_size) and counts["at_total"] < min_size:
            notes.append(
                f"达标样本量 {counts['at_total']} 低于要求 {min_size}（[TBD-V4d]）：本轮不足以支撑判定"
            )
            not_exercisable.append(
                {"dimension": "sample_size", "reason": f"at_threshold N={counts['at_total']} < {min_size}"}
            )
    if min_ratio < 1.0:
        not_exercisable.append(
            {
                "dimension": "visible_data_ratio_only",
                "reason": (
                    "v0 合成裁剪无法构造'角点达标但数据位比例低于阈值'的样本"
                    "（裁到数据列必然先裁掉边框角点）；该维度只能等 V4 实测"
                ),
            }
        )
    if counts["below_silent"] or counts["at_silent"]:
        failures.append(
            {
                "dimension": "protocol",
                "violation": "silent",
                "detail": "读码器出现静默（不输出也不带码报错）",
            }
        )

    thresholds_used = {
        "min_visible_corners ([TBD-V4a])": min_corners,
        "min_visible_data_ratio ([TBD-V4b])": min_ratio,
        "miss_rate_limit ([TBD-V4c])": miss_limit,
        "min_sample_size ([TBD-V4d])": min_size,
    }
    receipt = Receipt(
        suite="V4",
        simulated=True,
        sample_set_sha256=sample_set_sha256(descriptions(samples)),
        thresholds_used=thresholds_used,
        counts=counts,
        failures=failures,
        not_exercisable=not_exercisable,
        notes=notes,
        reader=reader_identity(reader),
    )
    report = receipt.finalize().to_dict()
    report["measured"] = {"miss_rate": miss_rate}
    return report


if __name__ == "__main__":
    from ._runner import run_cli

    raise SystemExit(run_cli("V4", run))
