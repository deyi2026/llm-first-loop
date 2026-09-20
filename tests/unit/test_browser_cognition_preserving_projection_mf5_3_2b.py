from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

import llm_loop.browser.perception as perception_module
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore

ROOT = Path(__file__).resolve().parents[2]
BASE = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)["base"]


def _object(object_id: str, *, coverage: str, kind: str = "generic", name: str = "") -> dict[str, Any]:
    return {
        "id": object_id,
        "kind": kind,
        "attributes": {"name": name} if name else {},
        "coverage": {"status": coverage, "sources": [], "blind_spots": [], "conflicts": []},
    }


def _grounding(identity_basis: str) -> dict[str, Any]:
    return {"identity_basis": identity_basis}


def test_mf5_3_2b_projection_order_is_complete_then_stable_then_opaque_id() -> None:
    objects = [
        _object("el_a_partial_stable", coverage="partial"),
        _object("el_b_complete_local", coverage="complete"),
        _object("el_d_complete_stable", coverage="complete"),
        _object("el_c_complete_stable", coverage="complete"),
        _object("el_e_partial_local", coverage="partial"),
    ]
    grounding = {
        "el_a_partial_stable": _grounding("dom_physical_identity"),
        "el_b_complete_local": _grounding("snapshot_local_ax_identity"),
        "el_c_complete_stable": _grounding("dom_physical_identity"),
        "el_d_complete_stable": _grounding("ax_backend_physical_identity"),
        "el_e_partial_local": _grounding("snapshot_local_ax_identity"),
    }
    objects_before = copy.deepcopy(objects)
    grounding_before = copy.deepcopy(grounding)

    ordered = perception_module._model_projection_order(objects, grounding)

    assert [obj["id"] for obj in ordered] == [
        "el_c_complete_stable",
        "el_d_complete_stable",
        "el_b_complete_local",
        "el_a_partial_stable",
        "el_e_partial_local",
    ]
    assert objects == objects_before
    assert grounding == grounding_before


def test_mf5_3_2b_equal_quality_tie_break_ignores_name_kind_and_task_semantics() -> None:
    objects = [
        _object("el_z", coverage="complete", kind="button", name="Save code"),
        _object("el_a", coverage="complete", kind="generic", name="irrelevant text"),
    ]
    grounding = {
        "el_z": _grounding("dom_physical_identity"),
        "el_a": _grounding("dom_physical_identity"),
    }

    ordered = perception_module._model_projection_order(objects, grounding)

    assert [obj["id"] for obj in ordered] == ["el_a", "el_z"]
    signature = inspect.signature(perception_module._model_projection_order)
    assert tuple(signature.parameters) == ("objects", "object_grounding")


def test_mf5_3_2b_snapshot_uses_quality_order_only_for_model_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "browser"))
    calls: list[list[str]] = []

    def reverse_projection(
        objects: list[dict[str, Any]], object_grounding: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        del object_grounding
        calls.append([str(obj["id"]) for obj in objects])
        return list(reversed(objects))

    monkeypatch.setattr(perception_module, "_model_projection_order", reverse_projection)
    result = adapter.snapshot("s1", copy.deepcopy(BASE), projection_limit=2)
    hydrated = adapter.hydrate("s1", result["snapshot"]["objects_ref"])

    assert calls
    canonical = hydrated["content"]
    canonical_ids = [str(obj["id"]) for obj in canonical]
    projected_ids = [str(obj["id"]) for obj in result["objects"]]
    assert canonical_ids == sorted(canonical_ids)
    assert projected_ids == list(reversed(canonical_ids))[:2]
    assert result["snapshot"]["projection"]["full_ref"] == result["snapshot"]["objects_ref"]
    assert len(canonical) == result["objects_projection"]["total"]
