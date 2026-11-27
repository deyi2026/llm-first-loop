"""V8 fail-closed（SPEC §11.2-V8）：注入故障样本，按类型分派期望行为。

- 漏检类（遮挡 / 超纠错码字 / 贴歪不可读）→ 不输出 + 计数上报（禁止静默）；
- 伪造 / 层级矛盾类（错 ID、复制靶标、级间位姿矛盾）→ STOP + 报警；
- 两类均要求"带错硬接 = 0"。

v0 只能演练漏检类：伪造 / 层级矛盾类的期望行为依赖回退状态机（F-1–F-5）与几何互证（M-2b），
二者均未实现——这些样本如实标 not_exercisable，不计入断言范围，也不据此宣称通过。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ._runner import KNOWN_INDICES, drive
from .receipt import Receipt, reader_identity, sample_set_sha256
from .synth import (
    FORGERY_REASONS,
    FORGERY_TYPES,
    LEAK_TYPES,
    crop_corners,
    descriptions,
    foreign_grid,
    index_with_dark_data_columns,
    make_sample,
    render_grid,
    render_tag,
    unreadable,
)


def build_samples(n: int = 1000, *, include_forgery: bool = True, seed: int = 0) -> list[dict]:
    """确定性故障样本集：漏检类与伪造类各占一半（include_forgery=False 时全部为漏检类）。"""
    if n < 1:
        raise ValueError("n must be >= 1")
    rng = np.random.default_rng(seed)
    leak_count = n // 2 if include_forgery else n
    forgery_count = n - leak_count
    samples: list[dict] = []
    dark_column_index = index_with_dark_data_columns(1)
    occlusions = 0
    for number in range(leak_count):
        fault = LEAK_TYPES[number % len(LEAK_TYPES)]
        # 遮挡类用带暗首列的码（裁剪后包围盒才贴左沿）；其余类型轮换已知码
        index = dark_column_index if fault == "occlusion" else KNOWN_INDICES[number % len(KNOWN_INDICES)]
        if fault == "occlusion":
            # 裁剪量按遮挡样本自身的序号轮换（上+左 / 仅左 / 左+上+右），不与故障类型同源取模
            image = crop_corners(render_tag(index), (occlusions % 3) + 1)
            occlusions += 1
        elif fault == "beyond_ec":
            image = render_grid(foreign_grid(index, n_flips=6, rng=rng))
        else:
            image = unreadable(render_tag(index), rng=rng)
        samples.append(
            make_sample("leak", f"leak_{number:04d}", fault, "no_output_and_counted", image)
        )
    placeholder = np.zeros((8, 8), dtype=np.uint8)
    for number in range(forgery_count):
        fault = FORGERY_TYPES[number % len(FORGERY_TYPES)]
        samples.append(
            make_sample("forgery", f"forgery_{number:04d}", fault, "stop_and_alarm", placeholder)
        )
    return samples


def run(
    reader: Any,
    *,
    config: dict | None = None,
    samples: list[dict] | None = None,
    seed: int = 0,
    n: int = 1000,
) -> dict:
    config = dict(config or {})
    include_forgery = config.get("include_forgery", True)
    if not isinstance(include_forgery, bool):
        # bool() 强转会把 "false" / null 静默变成另一个演练范围：范围一变回执就不可比，一律拒绝
        raise ValueError("V8 'include_forgery' must be a JSON boolean (true / false) when provided")
    if "n" in config:
        n = int(config["n"])
    samples = build_samples(n, include_forgery=include_forgery, seed=seed) if samples is None else samples
    exercised = [sample for sample in samples if sample["description"]["kind"] == "leak"]
    skipped = [sample for sample in samples if sample["description"]["kind"] == "forgery"]

    counts = {
        "total": len(samples),
        "leak_total": len(exercised),
        "leak_refused": 0,
        "leak_output": 0,
        "leak_silent": 0,
        "forgery_total": len(skipped),
        "forgery_exercised": 0,
    }
    failures: list[dict] = []
    for sample, record in zip(exercised, drive(reader, exercised), strict=True):
        fault = record["fault_type"]
        counts[f"leak_{fault}_total"] = counts.get(f"leak_{fault}_total", 0) + 1
        if record["outcome"] == "observation":
            counts["leak_output"] += 1
            failures.append(
                {
                    "sample_id": record["sample_id"],
                    "violation": "output_on_unreadable",
                    "detail": f"{fault}: reader output target_index={record.get('target_index')}",
                }
            )
        elif record["outcome"] == "refused":
            counts["leak_refused"] += 1
            counts[f"refused_code_{record['code']}"] = counts.get(f"refused_code_{record['code']}", 0) + 1
        else:
            counts["leak_silent"] += 1
            failures.append(
                {
                    "sample_id": record["sample_id"],
                    "violation": "silent",
                    "detail": f"{fault}: reader neither output nor raised a typed error ({record['outcome']})",
                }
            )

    not_exercisable: list[dict] = []
    for fault in FORGERY_TYPES:
        number = sum(1 for sample in skipped if sample["description"]["fault_type"] == fault)
        if number:
            not_exercisable.append({"fault_type": fault, "count": number, "reason": FORGERY_REASONS[fault]})

    receipt = Receipt(
        suite="V8",
        simulated=True,
        sample_set_sha256=sample_set_sha256(descriptions(samples)),
        thresholds_used={},
        counts=counts,
        failures=failures,
        not_exercisable=not_exercisable,
        reader=reader_identity(reader),
        notes=[
            "漏检类期望：不输出 + 计数上报（禁止静默）；伪造 / 层级矛盾类期望：STOP + 报警（SPEC §11.2-V8）",
            "带错硬接 = 0 只对已演练的漏检类样本断言；伪造类未演练，不据此宣称通过",
            f"leak 类拒绝原因计数：按读码器错误码分别统计（refused_code_*）",
        ],
    )
    return receipt.finalize().to_dict()


if __name__ == "__main__":
    from ._runner import run_cli

    raise SystemExit(run_cli("V8", run, supports_n=True))
