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


def test_example_manifest_kinds_match_registry_zero_drift() -> None:
    """独立审查 P1-2（2026-11-08）：example kinds 必须与权威 registry 零漂移。

    曾经 manifest.example.json 把 fs.write 标为 idempotent/supervised_only=false
    （registry 为 non_idempotent/True），example 形态不可实现且绕过不变量。
    任何 manifest* example 的 kind 条目都必须逐字段等于 registry。
    """
    from llm_loop.peer.kinds import KINDS

    examples = sorted(SCHEMA_DIR.glob("examples/manifest*.example.json"))
    assert examples, "至少应有一个 manifest example"
    for path in examples:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload["kinds"]:
            spec = KINDS.get(item["kind"])
            assert spec is not None, f"{path.name}: {item['kind']} 不在注册表"
            assert item["idempotency_class"] == spec.idempotency_class, (
                f"{path.name}: {item['kind']} idempotency_class 漂移"
            )
            assert item["supervised_only"] == spec.supervised_only, (
                f"{path.name}: {item['kind']} supervised_only 漂移"
            )


def test_wayland_manifest_example_is_schema_valid() -> None:
    """独立审查 P1-1（2026-11-08）：Wayland/none 形态必须是 schema 合法正例。"""
    from jsonschema import validators

    wayland = SCHEMA_DIR / "examples" / "manifest-wayland.example.json"
    assert wayland.is_file(), "应有 wayland 正例"
    schema = _load("manifest.schema.json")
    payload = json.loads(wayland.read_text(encoding="utf-8"))
    validator_cls = validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator_cls(schema).validate(payload)
