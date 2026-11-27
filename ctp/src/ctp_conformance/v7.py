"""V7 混合版本墙（SPEC §11.2-V7）：混合版本靶标墙对旧版读码器误读 = 0。

外来码字 = 在合法 36h11 码上翻转 ≥6 位、且四个取向下与码表的最小汉明距离都 > 5
（超出纠错能力，代表其他版本族 / 被破坏的码），或与 36h11 无关的图案。
读码器对它们输出任何 ID 即误读。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ._runner import KNOWN_INDICES, drive
from .receipt import Receipt, reader_identity, sample_set_sha256
from .synth import (
    descriptions,
    foreign_grid,
    make_sample,
    min_hamming_rotations,
    render_grid,
    render_tag,
    unrelated_grid,
)


def build_samples(seed: int = 0) -> list[dict]:
    """确定性样本集：已知族 + 外来码字 + 无关图案（同 seed 两次构造逐字节一致）。"""
    rng = np.random.default_rng(seed)
    samples: list[dict] = []
    for index in KNOWN_INDICES:
        samples.append(
            make_sample(
                "known", f"known_{index:03d}", "known_family", "decode", render_tag(index), target_index=index
            )
        )
    for number, index in enumerate(KNOWN_INDICES):
        grid = foreign_grid(index, n_flips=6, rng=rng)
        samples.append(
            make_sample(
                "foreign",
                f"foreign_{number:03d}",
                "foreign_codeword",
                "refuse",
                render_grid(grid),
                source_index=index,
                min_hamming_over_rotations=min_hamming_rotations(grid),
            )
        )
    for number in range(3):
        grid = unrelated_grid(rng)
        samples.append(
            make_sample(
                "foreign",
                f"unrelated_{number:03d}",
                "unrelated_pattern",
                "refuse",
                render_grid(grid),
                min_hamming_over_rotations=min_hamming_rotations(grid),
            )
        )
    return samples


def run(reader: Any, *, config: dict | None = None, samples: list[dict] | None = None, seed: int = 0) -> dict:
    """跑混合版本墙。config 只透传记录（V7 无阈值依赖）；返回回执字典。"""
    samples = build_samples(seed) if samples is None else samples
    results = drive(reader, samples)
    counts = {
        "total": len(samples),
        "known_total": 0,
        "known_decoded": 0,
        "known_refused": 0,
        "foreign_total": 0,
        "foreign_refused_unknown_version": 0,
        "foreign_refused_other": 0,
        "foreign_silent": 0,
        "misread": 0,
    }
    failures: list[dict] = []
    for record in results:
        if record["kind"] == "known":
            counts["known_total"] += 1
            counts["known_decoded" if record["outcome"] == "observation" else "known_refused"] += 1
            continue
        counts["foreign_total"] += 1
        if record["outcome"] == "observation":
            counts["misread"] += 1
            failures.append(
                {
                    "sample_id": record["sample_id"],
                    "violation": "misread",
                    "detail": (
                        f"reader output target_index={record.get('target_index')} "
                        f"for {record['fault_type']}"
                    ),
                }
            )
        elif record["outcome"] == "refused" and record["code"] == "unknown_version":
            counts["foreign_refused_unknown_version"] += 1
        elif record["outcome"] == "refused":
            counts["foreign_refused_other"] += 1
        else:
            counts["foreign_silent"] += 1
    receipt = Receipt(
        suite="V7",
        simulated=True,
        sample_set_sha256=sample_set_sha256(descriptions(samples)),
        thresholds_used=dict(config) if config else {},
        counts=counts,
        failures=failures,
        reader=reader_identity(reader),
        notes=[
            "混合版本墙：外来码字 / 无关图案被输出任何 ID 即误读，误读必须为 0（SPEC §11.2-V7、§10 VC-3）",
            "V7 无阈值依赖；config 若给出仅作记录",
            "已知族样本被拒读不计入 V7 失败（属漏检侧，由 V4 统计）",
        ],
    )
    return receipt.finalize().to_dict()


if __name__ == "__main__":
    from ._runner import run_cli

    raise SystemExit(run_cli("V7", run))
