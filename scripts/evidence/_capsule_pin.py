"""R9-P0-01 批 1/3 共享 helper：evidence runner 家族回放钉住历史协议 capsule=on.

生产默认 LFL_EVIDENCE_CAPSULE 已由 on 翻 off（2026-09-01，CORE9 终判生效后），
但 evidence runner 家族（r7/r7v2/r8/r10）的基准协议——matrix/frozen fixture、
fake LLM 的 recover 胶囊路由、frozen scorer 合同——固化于 capsule=on 的历史
文本形状。dry 回放与 real 复跑期间钉住 on 以受控复现历史条件，不随生产默认
漂移；结束后恢复进程原值。
"""

from __future__ import annotations

import contextlib
import os


@contextlib.contextmanager
def pinned_capsule_on():
    prior = os.environ.get("LFL_EVIDENCE_CAPSULE")
    os.environ["LFL_EVIDENCE_CAPSULE"] = "on"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("LFL_EVIDENCE_CAPSULE", None)
        else:
            os.environ["LFL_EVIDENCE_CAPSULE"] = prior
