"""runner 共用的小件：逐样本驱动读码器并归类结果；构造被测读码器（延迟导入 ctp_reader）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .receipt import error_code
from .synth import TIMESTAMP

KNOWN_INDICES = (0, 1, 7, 100, 586)


def drive(reader: Any, samples: list[dict]) -> list[dict[str, Any]]:
    """对每个样本调用 read()，把结果归成三类：observation / refused(code) / silent。

    runner 必须把任何异常归类——读码器"静默"（不输出也不带码报错）本身就是 V8 的违例，
    所以这里宽捕获，不向上冒泡。
    """
    results: list[dict[str, Any]] = []
    for sample in samples:
        description = sample["description"]
        record: dict[str, Any] = {
            "sample_id": description["sample_id"],
            "kind": description["kind"],
            "fault_type": description["fault_type"],
            "expected": description["expected"],
        }
        try:
            observation = reader.read(sample["image"], timestamp=TIMESTAMP)
        except Exception as error:  # noqa: BLE001 - 见模块说明：归类后写入回执，不允许静默
            code = error_code(error)
            record["outcome"] = "refused" if code else "silent_untyped"
            record["code"] = code
            record["error_type"] = type(error).__name__
        else:
            record["outcome"] = "observation" if observation is not None else "silent_none"
            record["target_index"] = getattr(observation, "target_index", None)
        results.append(record)
    return results


def build_reader(spec_path: str | Path) -> Any:
    """按声明式 JSON 构造被测读码器（B3）。延迟导入：本包顶层不依赖 ctp_reader。"""
    try:
        from ctp_calib.pixel import PinholeCamera
        from ctp_reader.config import ThresholdConfig
        from ctp_reader.gate import ReadGate
        from ctp_reader.reader import Reader
    except ImportError as error:  # B3 尚未落盘时给出明确原因，而不是含糊的 NameError
        raise RuntimeError(
            "ctp_reader / ctp_calib 不可导入：请确认 B3 读码器已落盘且 sys.path 含 ctp/src"
        ) from error

    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    camera = spec["camera"]
    thresholds = ThresholdConfig.from_file(spec["thresholds"])
    return Reader(
        gate=ReadGate(thresholds),
        camera=PinholeCamera(fx=camera["fx"], fy=camera["fy"], cx=camera["cx"], cy=camera["cy"]),
        tag_size_m=spec["tag_size_m"],
        sigma_px=spec["sigma_px"],
        coverage_factor_k=spec["coverage_factor_k"],
        reader_id=spec["reader_id"],
        reader_version=spec["reader_version"],
        frame_ref=spec["frame_ref"],
    )


def run_cli(suite: str, run_function: Any, *, supports_n: bool = False) -> int:
    """命令行入口：--simulated 必填（拒绝生成非 simulated 回执），输出 JSON 回执文件。"""
    import argparse

    parser = argparse.ArgumentParser(prog=f"ctp_conformance.{suite.lower()}")
    parser.add_argument("--simulated", action="store_true", required=True)
    parser.add_argument("--reader-spec", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--config", default=None, help="runner 配置（JSON 字符串）")
    if supports_n:
        parser.add_argument("--n", type=int, default=1000)
    arguments = parser.parse_args()
    config = json.loads(arguments.config) if arguments.config else {}
    if supports_n:
        config["n"] = arguments.n
    reader = build_reader(arguments.reader_spec)
    report = run_function(reader, config=config, seed=arguments.seed)
    target = Path(arguments.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{suite} verdict={report['verdict']} simulated={report['simulated']} receipt={target}")
    return 0 if report["verdict"] == "pass" else 1
