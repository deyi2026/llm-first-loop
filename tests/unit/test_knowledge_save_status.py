"""Positive-only Experience success status; failed/uncertain writes are not learning."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from llm_loop.core.message import ToolResultStatus
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.registry_experience import execute
from llm_loop.introspection.registry_host import RegistryHost


def _host(store: object) -> RegistryHost:
    # This adapter exercises only the experience_store member of RegistryHost.
    return cast(RegistryHost, SimpleNamespace(experience_store=store))


def _request(title: str) -> dict:
    return {
        "title": title,
        "scenario": "pytest fixture repair when expected input is unavailable",
        "solution": "先检查当前性验证：读取 fixture 的真实输入与错误行",
        "record_kind": "lesson",
        "verification_state": "unverified",
    }


def test_real_save_success_exact_ref_then_conflict_is_not_success(tmp_path) -> None:
    host = _host(ExperienceStore(tmp_path / "experiences"))
    original = execute("save_experience", _request("fixture repair"), host)
    assert original is not None and original.status is ToolResultStatus.SUCCESS
    assert "experience_ref=experience:EXPERIENCE-" in original.content
    collision = execute("save_experience", _request("fixture repair"), host)
    assert collision is not None and collision.status is ToolResultStatus.FAILURE
    assert "文件冲突" in collision.content
    assert len(list((tmp_path / "experiences").glob("EXPERIENCE-*.md"))) == 1


def test_refine_missing_is_not_success(tmp_path) -> None:
    host = _host(ExperienceStore(tmp_path / "experiences"))
    result = execute(
        "refine_experience",
        {"experience_id": "EXPERIENCE-20261008-nonexistent", "action": "archive"},
        host,
    )
    assert result is not None and result.status is ToolResultStatus.FAILURE
    assert "[未找到]" in result.content


def test_uncertain_or_conflict_prefix_never_masquerades_as_save_success(tmp_path) -> None:
    class UncertainStore:
        def save(self, _doc):
            raise FileExistsError("already exists")

    fake = _host(UncertainStore())
    result = execute("save_experience", _request("already exists"), fake)
    assert result is not None and result.status is ToolResultStatus.FAILURE
    assert "[save_experience] 文件冲突" in result.content
