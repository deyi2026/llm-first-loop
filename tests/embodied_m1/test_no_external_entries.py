"""Static guard: embodied_sim must have no network or hardware entry points."""
from __future__ import annotations

from pathlib import Path

FORBIDDEN_IMPORTS = (
    "socket", "ssl", "requests", "urllib", "http", "ftplib", "smtplib",
    "subprocess", "serial", "hid", "usb", "websocket",
)


def test_no_network_or_hardware_imports():
    pkg = Path(__file__).resolve().parents[2] / "src" / "llm_loop" / "embodied_sim"
    assert pkg.is_dir()
    offenders = []
    for py in sorted(pkg.glob("*.py")):
        src = py.read_text(encoding="utf-8")
        for mod in FORBIDDEN_IMPORTS:
            if f"import {mod}" in src or f"from {mod}" in src:
                offenders.append(f"{py.name}: {mod}")
    assert offenders == [], f"network/hardware imports found: {offenders}"
