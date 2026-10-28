"""svc_deploy: update 缺省 restart 目标推导——单一实现源（runtime 与工具面共用）.

T2（2026-10-27 收紧）：规则从“路径名含服务名子串 → 该服务，否则 all”改为
token 精确匹配——code_root 的 basename 按非字母数字切分为 token，恰好含且
仅含一个服务名 token 才推导（feishu-code→feishu、mirror-web→web、
mirror-learning→learning 仍成立；shared-root 无服务名、web-and-feishu 多服
务歧义 → 不推导）。推导不出时调用方必须显式拒绝（NEEDS_TARGET，附可选
target 列表与一条示例命令），禁止静默兜底 all；显式传参永远优先，回执仅在
目标由推导得来时标注 derived_from（basename 与命中 token）。

独立模块原因：runtime/service_control.py 若模块级导入
tools/builtin/service_control.py 会构成循环导入——tools 顶部已导入 runtime，
实测 tools 先导入即 ``ImportError: partially initialized module``（探针验证
后已还原）。故抽出本叶子模块供两侧共用，推导规则只此一份。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# 可推导的服务名集合（不含 all：all 只能显式指定，不可由路径推导）。
DERIVABLE_SERVICE_TARGETS: tuple[str, ...] = ("web", "feishu", "learning")

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


@dataclass(frozen=True)
class RestartTargetDerivation:
    """推导结果；``target is None`` 表示推导不出（调用方必须拒绝，不得兜底 all）。"""

    basename: str
    matched_token: str = ""
    target: str | None = None

    @property
    def derived(self) -> bool:
        return self.target is not None


def tokenize_basename(name: str) -> list[str]:
    """basename 按非字母数字切分为小写 token（空片丢弃）。"""
    return [token for token in _NON_ALNUM.split(name.lower()) if token]


def derive_restart_target(code_root: str) -> RestartTargetDerivation:
    """token 精确推导 update 缺省 restart 目标；无命中/多服务歧义 → target=None."""
    basename = Path(code_root).expanduser().name
    matched = [
        service
        for service in DERIVABLE_SERVICE_TARGETS
        if service in tokenize_basename(basename)
    ]
    if len(matched) == 1:
        return RestartTargetDerivation(
            basename=basename, matched_token=matched[0], target=matched[0]
        )
    return RestartTargetDerivation(basename=basename)
