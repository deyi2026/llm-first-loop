from __future__ import annotations

import importlib.util
from pathlib import Path


def _load(name: str, rel: str):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(name, root / rel)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_ioreg_performance_statistics() -> None:
    mod = _load("gpu_timeline", "scripts/telemetry/gpu_timeline.py")
    text = (
        '"PerformanceStatistics" = {'
        '"Tiler Utilization %"=7,"Renderer Utilization %"=33,'
        '"Device Utilization %"=91,"In use system memory"=1234,'
        '"Alloc system memory"=5678}'
    )
    got = mod.parse_ioreg(text)
    assert got["device_utilization_pct"] == 91
    assert got["renderer_utilization_pct"] == 33
    assert got["tiler_utilization_pct"] == 7
    assert got["in_use_system_memory_bytes"] == 1234


def test_gpu_window_summary_is_fact_only() -> None:
    mod = _load("gpu_corr", "scripts/telemetry/correlate_gpu_events.py")
    rows = [
        {"device_utilization_pct": 100, "process_cpu_pct": 80.0},
        {"device_utilization_pct": 90, "process_cpu_pct": 70.0},
        {"device_utilization_pct": 20, "process_cpu_pct": 10.0},
        {"device_utilization_pct": 10, "process_cpu_pct": 5.0},
    ]
    got = mod.summarize_window(rows)
    assert got["gpu_ge80_ratio"] == 0.5
    assert got["gpu_le30_ratio"] == 0.5
    assert got["longest_low_run_samples"] == 2
    assert "certainty" not in got
    assert "quality" not in got
