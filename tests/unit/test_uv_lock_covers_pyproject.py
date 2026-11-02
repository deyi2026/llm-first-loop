"""uv.lock ↔ pyproject 依赖一致性护栏（2026-11-02 CI 红根因）。

2026-10-29 的 c4d75cf96 给 pyproject 加了 wecom-aibot-python-sdk==1.0.2，但没有重生成
uv.lock。CI 用 `uv sync --frozen` 装依赖：--frozen 只照 lock 装、不做一致性校验，于是
CI 的 venv 里没有 aibot；2026-11-02 新增的 tests/conftest.py 环境预检在收集阶段判
env_missing_dependency 并以 exit 10 中止，pytest 与 D4 两个 job 同时红。

本地能绿是因为 .venv 里手工装过 aibot——lock 漂移在单测层面完全不可见，只能等 CI 说话。
本文件把「pyproject 声明的东西必须在 lock 里」变成可机械判定的单测：不联网、不调 uv，
只解析两个文件。下次再有人加依赖忘了 `uv lock`，先红在这里，而不是红在 CI。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _ROOT / "pyproject.toml"
_LOCK = _ROOT / "uv.lock"

_CANON_SEP = re.compile(r"[-_.]+")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_EXACT_PIN = re.compile(r"^==\s*([0-9][0-9A-Za-z.+!-]*)$")


def _canonical(name: str) -> str:
    """PEP 503 归一：大小写与 -/_/. 都视为同一分发包。"""
    return _CANON_SEP.sub("-", name.strip()).lower()


def _requirement_name(requirement: str) -> str:
    match = _NAME.match(requirement.strip())
    if match is None:
        raise AssertionError(f"无法从依赖声明里解析出包名: {requirement!r}")
    return _canonical(match.group(0))


def _exact_pin(requirement: str) -> str | None:
    """只对 `name==1.2.3` 这种可机械比对的精确钉版本返回版本号，其余返回 None。

    区间约束（>=、~=）不在这里判——lock 里的解析结果本来就允许高于下限，
    把区间也钉死会让正常升级变成假红。
    """
    text = requirement.strip()
    match = _NAME.match(text)
    if match is None:
        return None
    spec = text[match.end():].split(";", 1)[0].strip()
    pinned = _EXACT_PIN.match(spec)
    return pinned.group(1) if pinned else None


def _declared_requirements() -> list[str]:
    document = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    project = document["project"]
    declared = list(project.get("dependencies") or [])
    for group in (project.get("optional-dependencies") or {}).values():
        declared.extend(group or [])
    # [dependency-groups]（PEP 735）现在还没出现在 pyproject 里，但它同样是"声明的
    # 依赖"：哪天真加了 dev 组，缺项检查不能装作没看见（独立审查 P2-2）。
    for group in (document.get("dependency-groups") or {}).values():
        declared.extend(item for item in group or [] if isinstance(item, str))
    return declared


def _locked_versions() -> dict[str, str]:
    lock = tomllib.loads(_LOCK.read_text(encoding="utf-8"))
    return {
        _canonical(package["name"]): str(package.get("version", ""))
        for package in lock.get("package") or []
    }


def test_lockfile_covers_every_declared_dependency() -> None:
    locked = _locked_versions()
    missing = sorted(
        {
            _requirement_name(req)
            for req in _declared_requirements()
            if _requirement_name(req) not in locked
        }
    )
    assert not missing, (
        "uv.lock 缺少 pyproject 声明的依赖 "
        f"{missing}；CI 用 `uv sync --frozen` 照 lock 装依赖，"
        "缺项不会报错而是装出残缺 venv。修法：在仓库根跑 `uv lock` 并提交 uv.lock。"
    )


def test_exact_pins_match_locked_version() -> None:
    locked = _locked_versions()
    mismatched = [
        (name, pinned, locked[name])
        for name, pinned in (
            (_requirement_name(req), _exact_pin(req)) for req in _declared_requirements()
        )
        if pinned is not None and name in locked and locked[name] != pinned
    ]
    assert not mismatched, (
        f"pyproject 精确钉的版本与 uv.lock 不一致: {mismatched}；"
        "多半是改了 pyproject 的 ==x.y.z 却没重跑 `uv lock`。"
    )


def test_guard_inputs_are_not_vacuous() -> None:
    """护栏自身的防真空：解析器坏掉时两个集合都会空，缺项检查会假装通过。"""
    declared = _declared_requirements()
    locked = _locked_versions()
    assert len(declared) >= 10, f"只解析到 {len(declared)} 条依赖声明，解析器可能已失效"
    assert len(locked) >= 50, f"只解析到 {len(locked)} 个 lock 包，解析器可能已失效"
    # 被本次 CI 红卡住的那个包必须在两侧都在——它同时是回归样本。
    assert "wecom-aibot-python-sdk" in {_requirement_name(r) for r in declared}
    assert "wecom-aibot-python-sdk" in locked
