#!/usr/bin/env python3
"""校验 lfl.peer.v1 契约产物：schema 自洽、示例通过、应拦输入被拒。

设计约束（不是本脚本的发明）：
- ``reason_code`` 是封闭枚举，receipt schema 与 reason-codes.json 必须零漂移。
- ``inject_type`` 首版恒 false（D11），schema 用 const 表达，原地放宽会直接失败。
- 语义不变量（非 JSON Schema 能表达）：非幂等 kind 必须 supervised_only。

用法::

    python3 scripts/verify_peer_schemas.py
    python3 scripts/verify_peer_schemas.py --dir docs/schemas/lfl.peer.v1

退出码 0 表示全部通过；1 表示有失败项。``date-time`` 负例在缺
``rfc3339-validator`` 时记为 skipped 而不是 pass——未校验不得冒充通过。
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import FormatChecker, validators
from jsonschema.exceptions import SchemaError, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = REPO_ROOT / "docs" / "schemas" / "lfl.peer.v1"
_ISO_HINT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

OK = "ok"
FAIL = "FAIL"
SKIP = "skipped"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_strings(node: Any, path: str = "") -> Any:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def _make_validator(schema: dict[str, Any], fmt: FormatChecker) -> Any:
    cls = validators.validator_for(schema)
    return cls(schema, format_checker=fmt)


def _check_iso_strings(payload: Any, where: str, rows: list[tuple[str, str, str, str]]) -> None:
    """format 校验器缺席时的兜底：示例里的 ISO 时间必须真能被解析。"""
    for path, value in _iter_strings(payload):
        if not _ISO_HINT.match(value):
            continue
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            rows.append(("iso-fallback", f"{where}{path}", FAIL, f"unparsable: {value}"))


def _build_negatives(examples: dict[str, Any]) -> list[dict[str, Any]]:
    denied = copy.deepcopy(examples["receipt-denied"])
    no_reason = copy.deepcopy(denied)
    no_reason.pop("reason_code", None)

    bad_code = copy.deepcopy(denied)
    bad_code["reason_code"] = "something_else"

    ok_receipt = copy.deepcopy(examples["receipt-succeeded"])
    ok_receipt["reason_code"] = "timeout"

    extra_field = copy.deepcopy(denied)
    extra_field["narrative"] = "我猜它失败了"

    manifest_type = copy.deepcopy(examples["manifest"])
    manifest_type["desktop"]["inject_type"] = True

    manifest_click = copy.deepcopy(examples["manifest"])
    manifest_click["desktop"]["screenshot"] = False

    grant_no_expiry = copy.deepcopy(examples["grant"])
    grant_no_expiry.pop("expires_at", None)

    grant_rel_path = copy.deepcopy(examples["grant"])
    grant_rel_path["allowed_paths"] = ["relative/project"]

    pair_short = copy.deepcopy(examples["pair-offer"])
    pair_short["short_fingerprint"] = "too-short"

    task_bad_kind = copy.deepcopy(examples["task-submit"])
    task_bad_kind["kind"] = "Shell Exec"

    task_no_effect = copy.deepcopy(examples["task-submit"])
    task_no_effect.pop("effect_id", None)

    grant_bad_time = copy.deepcopy(examples["grant"])
    grant_bad_time["expires_at"] = "not-a-date"

    return [
        {"name": "receipt denied 缺 reason_code", "schema": "receipt", "payload": no_reason},
        {"name": "receipt reason_code 越出枚举", "schema": "receipt", "payload": bad_code},
        {"name": "receipt succeeded 带 reason_code", "schema": "receipt", "payload": ok_receipt},
        {"name": "receipt 未知字段", "schema": "receipt", "payload": extra_field},
        {"name": "manifest inject_type=true", "schema": "manifest", "payload": manifest_type},
        {"name": "manifest 点击但无采集", "schema": "manifest", "payload": manifest_click},
        {"name": "grant 缺 expires_at", "schema": "grant", "payload": grant_no_expiry},
        {"name": "grant 相对路径", "schema": "grant", "payload": grant_rel_path},
        {"name": "pair 短指纹格式错", "schema": "pair-offer", "payload": pair_short},
        {"name": "task kind 非法字符", "schema": "task-submit", "payload": task_bad_kind},
        {"name": "task 缺 effect_id", "schema": "task-submit", "payload": task_no_effect},
        {"name": "grant expires_at 非时间", "schema": "grant", "payload": grant_bad_time,
         "requires_format": True},
    ]


def _peer_kind_registry() -> dict[str, tuple[str, bool]] | None:
    """权威 kind 注册表（src/llm_loop/peer/kinds.py）；不可导入返回 None（记 SKIP 不冒充通过）。"""
    src_root = str(REPO_ROOT / "src")
    if src_root not in sys.path:
        sys.path.insert(0, src_root)
    try:
        from llm_loop.peer.kinds import KINDS  # noqa: PLC0415

        return {
            spec.kind: (spec.idempotency_class, spec.supervised_only)
            for spec in KINDS.values()
        }
    except Exception:  # noqa: BLE001 — registry 不可得按未检查处理，不伪造结论
        return None


def _check_invariants(base: Path, examples: dict[str, Any],
                      rows: list[tuple[str, str, str, str]]) -> None:
    codes = sorted(_load(base / "reason-codes.json")["codes"])
    receipt = _load(base / "receipt.schema.json")
    enum = sorted(receipt["$defs"]["reason_code"]["enum"])
    if codes == enum:
        rows.append(("consistency", "reason_code enum == reason-codes.json", OK, f"{len(codes)} codes"))
    else:
        only_json = sorted(set(codes) - set(enum))
        only_schema = sorted(set(enum) - set(codes))
        rows.append(("consistency", "reason_code enum == reason-codes.json", FAIL,
                     f"only_json={only_json} only_schema={only_schema}"))

    # 独立审查 P1-2（2026-11-08）：example 的 kinds 声明曾与权威 registry 漂移
    # （example 标 idempotent/supervised_only=false 绕过不变量）。修复后任何
    # manifest* example 的每个 kind 条目都必须与 registry 零漂移。
    registry = _peer_kind_registry()
    for stem in sorted(k for k in examples if k == "manifest" or k.startswith("manifest-")):
        for item in examples[stem]["kinds"]:
            label = f"{stem}:{item['kind']}"
            supervised = item["idempotency_class"] == "non_idempotent"
            if supervised and not item["supervised_only"]:
                rows.append(("invariant", f"non_idempotent => supervised_only ({label})",
                             FAIL, "非幂等 kind 未标记 supervised_only"))
            else:
                rows.append(("invariant", f"non_idempotent => supervised_only ({label})", OK, ""))
            if registry is None:
                rows.append(("consistency", f"example kinds == registry ({label})",
                             SKIP, "registry 不可导入"))
                continue
            spec = registry.get(item["kind"])
            if spec is None:
                rows.append(("consistency", f"example kinds == registry ({label})",
                             FAIL, "kind 不在注册表"))
            elif spec != (item["idempotency_class"], item["supervised_only"]):
                rows.append(("consistency", f"example kinds == registry ({label})",
                             FAIL, f"registry={spec} example 漂移"))
            else:
                rows.append(("consistency", f"example kinds == registry ({label})", OK, ""))

    grant = examples["grant"]
    if grant["tasks_used"] <= grant["max_tasks_total"]:
        rows.append(("invariant", "grant tasks_used <= max_tasks_total", OK,
                     f"{grant['tasks_used']}/{grant['max_tasks_total']}"))
    else:
        rows.append(("invariant", "grant tasks_used <= max_tasks_total", FAIL, "超额使用"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 lfl.peer.v1 schema 契约")
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help="schema 目录")
    args = parser.parse_args(argv)

    base = Path(args.dir)
    if not base.is_dir():
        print(f"[FAIL] schema 目录不存在: {base}")
        return 1

    schema_paths = sorted(base.glob("*.schema.json"))
    example_paths = sorted((base / "examples").glob("*.json"))
    if not schema_paths:
        print(f"[FAIL] 未找到 *.schema.json: {base}")
        return 1

    fmt = FormatChecker()
    format_available = "date-time" in fmt.checkers
    rows: list[tuple[str, str, str, str]] = []
    schemas: dict[str, dict[str, Any]] = {}

    for path in schema_paths:
        name = path.name.removesuffix(".schema.json")
        try:
            schema = _load(path)
            validators.validator_for(schema).check_schema(schema)
        except (json.JSONDecodeError, SchemaError) as exc:
            rows.append(("schema", path.name, FAIL, str(exc).splitlines()[0]))
            continue
        schemas[name] = schema
        rows.append(("schema", path.name, OK, ""))

    examples: dict[str, Any] = {}
    for path in example_paths:
        stem = path.name.removesuffix(".example.json")
        schema_name = next(
            (name for name in sorted(schemas, key=len, reverse=True)
             if stem == name or stem.startswith(f"{name}-")),
            None,
        )
        if schema_name is None:
            rows.append(("example", path.name, FAIL, f"无同名 schema: {stem}"))
            continue
        payload = _load(path)
        examples[stem] = payload
        try:
            _make_validator(schemas[schema_name], fmt).validate(payload)
        except ValidationError as exc:
            rows.append(("example", path.name, FAIL, exc.message))
            continue
        rows.append(("example", path.name, OK, ""))
        _check_iso_strings(payload, path.name, rows)

    if "receipt-denied" in examples and "receipt-succeeded" in examples:
        for case in _build_negatives(examples):
            schema = schemas.get(case["schema"])
            if schema is None:
                rows.append(("negative", case["name"], SKIP, "schema 缺失"))
                continue
            try:
                _make_validator(schema, fmt).validate(case["payload"])
            except ValidationError:
                rows.append(("negative", case["name"], OK, "已拒绝"))
            else:
                if case.get("requires_format") and not format_available:
                    rows.append(("negative", case["name"], SKIP, "date-time 未启用校验"))
                else:
                    rows.append(("negative", case["name"], FAIL, "应拒绝却通过"))

        _check_invariants(base, examples, rows)

    width = max(len(f"[{kind}] {name}") for kind, name, _, _ in rows) + 2
    for kind, name, status, detail in rows:
        label = f"[{kind}] {name}"
        suffix = f"  {detail}" if detail else ""
        print(f"{label:<{width}} {status}{suffix}")

    failed = [row for row in rows if row[2] == FAIL]
    skipped = [row for row in rows if row[2] == SKIP]
    counts = {kind: sum(1 for row in rows if row[0] == kind) for kind in
              ("schema", "example", "negative", "invariant", "consistency", "iso-fallback")}
    print()
    print("counts: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    if not format_available:
        print("note: rfc3339-validator 未安装，date-time 负例记 skipped；"
              "示例时间字段已用 fromisoformat 兜底校验")
    if failed:
        print(f"RESULT: FAIL ({len(failed)} failed, {len(skipped)} skipped)")
        return 1
    print(f"RESULT: PASS ({len(rows)} checks, {len(skipped)} skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
