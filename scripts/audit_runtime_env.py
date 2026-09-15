#!/usr/bin/env python3
"""AST-only inventory for direct process-environment access in LFL source.

This tool never imports application modules and never reads environment *values*.
It records only source locations/API shapes/key names so it is safe to persist as
configuration-debt evidence and to use as a one-way CI ratchet.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SECRET_RE = re.compile(r"(?:API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|(?:^|_)AK$|(?:^|_)SK$)")
_BOOTSTRAP_KEYS = {
    "PATH",
    "HOME",
    "TMPDIR",
    "PYTHONPATH",
    "LFL_WORKSPACE_ROOT",
    "LFL_ALLOW_RUNTIME_OVERRIDE",
    "LFL_ENV_FILE",
    "LFL_CONFIG_FILE",
}
_DEBUG_PREFIXES = (
    "ERR1210_",
    "LLM_PAYLOAD_TRACE",
    "CACHE_TELEMETRY_",
    "COG_RUNTIME_TELEMETRY",
    "LMS_",
    "LOCAL_ENABLE_THINKING",
    "TEST_",
)


@dataclass(frozen=True)
class EnvAccess:
    file: str
    scope: str
    op: str
    key: str
    module_import: bool

    @property
    def signature(self) -> str:
        return "|".join((self.file, self.scope, self.op, self.key))


class _Scanner(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.scope: list[str] = []
        self.items: list[EnvAccess] = []
        self.parents: dict[ast.AST, ast.AST] = {}

    def prepare(self, tree: ast.AST) -> None:
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[child] = parent

    def _scope(self) -> str:
        return "/".join(self.scope) if self.scope else "<module>"

    def _add(self, node: ast.AST, op: str, key: str) -> None:
        self.items.append(
            EnvAccess(
                self.rel,
                self._scope(),
                op,
                key,
                not self.scope,
            )
        )

    @staticmethod
    def _key(node: ast.AST | None) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return "<dynamic>"

    @staticmethod
    def _is_environ(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_key_read = isinstance(func, ast.Attribute) and (
            (func.attr == "get" and self._is_environ(func.value))
            or (
                func.attr == "getenv"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            )
        )
        if is_key_read:
            self._add(node, "read", self._key(node.args[0] if node.args else None))
        elif isinstance(func, ast.Attribute) and self._is_environ(func.value):
            # items/copy/keys/etc expose the whole environment rather than one key.
            self._add(node, f"bulk:{func.attr}", "<all>")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_environ(node.value):
            op = "write" if isinstance(node.ctx, ast.Store) else "read"
            self._add(node, op, self._key(node.slice))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._is_environ(node):
            parent = self.parents.get(node)
            handled = (
                isinstance(parent, (ast.Attribute, ast.Subscript))
                or (
                    isinstance(parent, ast.Call)
                    and isinstance(parent.func, ast.Attribute)
                    and parent.func.value is node
                )
            )
            if not handled:
                self._add(node, "bulk:raw", "<all>")
        self.generic_visit(node)


def scan_tree(root: Path) -> list[EnvAccess]:
    items: list[EnvAccess] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        scanner = _Scanner(rel)
        scanner.prepare(tree)
        scanner.visit(tree)
        items.extend(scanner.items)
    return items


def classify_key(key: str) -> str:
    if key in {"<dynamic>", "<all>"}:
        return "dynamic_or_bulk"
    if key in _BOOTSTRAP_KEYS:
        return "bootstrap_os"
    if _SECRET_RE.search(key):
        return "secret"
    if key.startswith(_DEBUG_PREFIXES):
        return "debug_test"
    return "business_config"


def build_inventory(items: list[EnvAccess]) -> dict[str, Any]:
    signatures = Counter(item.signature for item in items)
    reads: Counter[str] = Counter()
    writes: Counter[str] = Counter()
    module_reads: Counter[str] = Counter()
    files: dict[str, set[str]] = defaultdict(set)
    for item in items:
        if item.op == "write":
            writes[item.key] += 1
        else:
            reads[item.key] += 1
        if item.module_import and item.op != "write":
            module_reads[item.key] += 1
        files[item.key].add(item.file)

    all_keys = set(reads) | set(writes) | set(module_reads) | set(files)
    keys: dict[str, dict[str, Any]] = {}
    for key in sorted(all_keys):
        keys[key] = {
            "class": classify_key(key),
            "reads": reads[key],
            "writes": writes[key],
            "module_import_reads": module_reads[key],
            "files": sorted(files[key]),
        }
    classes = Counter(classify_key(key) for key in all_keys)
    return {
        "schema_version": 1,
        "access_count": len(items),
        "unique_key_count": len(all_keys),
        "file_count": len({item.file for item in items}),
        "module_import_access_count": sum(item.module_import for item in items),
        "class_key_counts": dict(sorted(classes.items())),
        "keys": keys,
        "signature_counts": dict(sorted(signatures.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default="src")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()
    inventory = build_inventory(scan_tree(Path(args.src)))
    text = json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_path:
        Path(args.json_path).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
