"""溯源标记恒等式校验（tasks 2.3，design §2.1.3-P1 校验落点 2，spec 6.1-2）.

恒等式：program_origin == (origin_layer != "user_instruction")

违反即标记失真：程序内容取得 user_instruction 判定。校验/纠正仅作用于
新写入，存量消息不回溯不清洗（spec 4.5-1）；异常 fail-open 放行 + 告警
（spec 4.2-1）。
"""

from __future__ import annotations

import logging
from typing import Any

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata

logger = logging.getLogger(__name__)

ORIGIN_LAYER_KEY = "origin_layer"
PROGRAM_ORIGIN_KEY = "program_origin"


def metadata_satisfies_invariant(metadata: Any) -> bool | None:
    """恒等式判定：True/False；缺键（无 metadata 存量形态）返回 None（fail-open）。"""
    if not isinstance(metadata, dict):
        return None
    layer = metadata.get(ORIGIN_LAYER_KEY)
    po = metadata.get(PROGRAM_ORIGIN_KEY)
    if layer is None or po is None:
        return None
    return bool(po) == (str(layer) != str(InjectionLayer.USER_INSTRUCTION.value))


def correct_mislabeled_metadata(metadata: Any, *, injection_kind: str = "leak_downgrade") -> dict:
    """纠正失真 metadata 为程序附录层标记（经单一真相源重构造）.

    保留原 metadata 中恒等式两键之外的可选键（turn_ref 等既有契约字段），
    恒等式两键以重构造值为准。
    """
    preserved = {
        k: v
        for k, v in (metadata or {}).items()
        if k not in (ORIGIN_LAYER_KEY, PROGRAM_ORIGIN_KEY)
    } if isinstance(metadata, dict) else {}
    return origin_metadata(
        InjectionLayer.PROGRAM_RECOVERY,
        injection_kind=injection_kind,
        **preserved,
    )
