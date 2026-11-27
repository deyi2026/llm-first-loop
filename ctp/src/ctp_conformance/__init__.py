"""CTP 一致性 runner 骨架（计划 §4.2 B7）：V4 / V7 / V8，合成数据，机器可读回执。

v0 只跑合成样本：回执 simulated 恒为真，不构成任何门槛实测证据（SPEC §11.2、计划 §0.4）。
读码器按协议注入（read() → ctp_contract.Observation，失败抛带 code 的异常），
本包顶层不 import ctp_reader。
"""

from __future__ import annotations

from .receipt import FAIL, INDETERMINATE, PASS, Receipt, sample_set_sha256
from .v4 import run as run_v4
from .v7 import run as run_v7
from .v8 import run as run_v8

__all__ = [
    "FAIL",
    "INDETERMINATE",
    "PASS",
    "Receipt",
    "run_v4",
    "run_v7",
    "run_v8",
    "sample_set_sha256",
]
