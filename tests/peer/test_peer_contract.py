"""契约不变量：运行期镜像必须与 docs/schemas/lfl.peer.v1 完全一致。"""
from __future__ import annotations

import json
from pathlib import Path

from llm_loop.peer.errors import REASON_CODES
from llm_loop.peer.kinds import DEFAULT_KINDS
from llm_loop.peer.models import GRANT_STATES
from llm_loop.peer.state import TASK_STATES

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "lfl.peer.v1"


def _load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_reason_codes_match_contract() -> None:
    contract = set(_load("reason-codes.json")["codes"])
    assert contract == set(REASON_CODES)
    assert len(REASON_CODES) == 36


def test_receipt_state_enum_matches_state_machine() -> None:
    receipt = _load("receipt.schema.json")
    enum = set(receipt["$defs"]["state"]["enum"])
    assert enum == set(TASK_STATES)


def test_grant_state_enum_matches_models() -> None:
    grant = _load("grant.schema.json")
    assert set(grant["properties"]["state"]["enum"]) == set(GRANT_STATES)


def test_non_idempotent_kinds_are_supervised_only() -> None:
    for spec in DEFAULT_KINDS:
        if spec.idempotency_class == "non_idempotent":
            assert spec.supervised_only, spec.kind


def test_kind_names_are_namespaced() -> None:
    for spec in DEFAULT_KINDS:
        assert "." in spec.kind
