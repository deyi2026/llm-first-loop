#!/usr/bin/env python3
"""AST-only inventory for direct process-environment access in LFL source.

This tool never imports application modules and never reads environment *values*.
It records only source locations/API shapes/key names so it is safe to persist as
configuration-debt evidence and to use as a one-way CI ratchet.

Schema v2 closes two blind spots from the first inventory:
- aliases such as ``import os as _os`` / ``from os import getenv as _getenv``;
- local literal wrappers such as ``_env_float("KEY", default)`` whose body performs
  the actual dynamic ``os.environ.get(name)``.  Wrapper projections are reported
  separately from physical/direct accesses so the original debt metric stays
  mechanically interpretable while import-time execution is no longer hidden.
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
_DYNAMIC_SECRET_EXPR_RE = re.compile(
    r"(?:api[_-]?key|secret|token|password|credential).*(?:env|name)"
    r"|(?:env|name).*(?:api[_-]?key|secret|token|password|credential)",
    re.I,
)
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
    origin: str = "direct"  # direct | literal_helper | dynamic_helper
    key_expr: str = ""
    class_hint: str = ""

    @property
    def signature(self) -> str:
        # Keep the historical four-field signature stable.  Direct/helper debt is
        # frozen in separate maps in schema v2, so origin need not enter the key.
        return "|".join((self.file, self.scope, self.op, self.key))

    @property
    def access_class(self) -> str:
        return self.class_hint or classify_key(self.key)


@dataclass(frozen=True)
class _Aliases:
    os_modules: frozenset[str]
    environs: frozenset[str]
    getenvs: frozenset[str]


@dataclass(frozen=True)
class _WrapperAccess:
    param_name: str
    positional_index: int | None
    op: str


@dataclass(frozen=True)
class _WrapperSpec:
    name: str
    accesses: tuple[_WrapperAccess, ...]


def _collect_aliases(tree: ast.AST) -> _Aliases:
    os_modules = {"os"}
    environs: set[str] = set()
    getenvs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_modules.add(alias.asname or "os")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                bound = alias.asname or alias.name
                if alias.name == "environ":
                    environs.add(bound)
                elif alias.name == "getenv":
                    getenvs.add(bound)
    return _Aliases(frozenset(os_modules), frozenset(environs), frozenset(getenvs))


def _is_environ(node: ast.AST, aliases: _Aliases) -> bool:
    if isinstance(node, ast.Name) and node.id in aliases.environs:
        return True
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id in aliases.os_modules
    )


def _is_getenv(node: ast.AST, aliases: _Aliases) -> bool:
    if isinstance(node, ast.Name) and node.id in aliases.getenvs:
        return True
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "getenv"
        and isinstance(node.value, ast.Name)
        and node.value.id in aliases.os_modules
    )


def _safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive for future AST variants
        return type(node).__name__


def _key_info(node: ast.AST | None) -> tuple[str, str, str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, repr(node.value), ""
    expr = _safe_unparse(node)
    hint = "dynamic_secret" if expr and _DYNAMIC_SECRET_EXPR_RE.search(expr) else ""
    return "<dynamic>", expr, hint


def _call_key_node(node: ast.Call, aliases: _Aliases) -> ast.AST | None:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "get" and _is_environ(func.value, aliases):
        return node.args[0] if node.args else None
    if _is_getenv(func, aliases):
        return node.args[0] if node.args else None
    return None


def _function_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[list[str], set[str]]:
    positional = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args)]
    all_params = set(positional)
    all_params.update(arg.arg for arg in node.args.kwonlyargs)
    if node.args.vararg is not None:
        all_params.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        all_params.add(node.args.kwarg.arg)
    return positional, all_params


class _WrapperProbe(ast.NodeVisitor):
    """Find env operations whose key is one parameter of one top-level helper."""

    def __init__(self, params: set[str], positional: list[str], aliases: _Aliases) -> None:
        self.params = params
        self.positional = positional
        self.aliases = aliases
        self.accesses: list[_WrapperAccess] = []

    def _record(self, key_node: ast.AST | None, op: str) -> None:
        if not isinstance(key_node, ast.Name) or key_node.id not in self.params:
            return
        try:
            idx: int | None = self.positional.index(key_node.id)
        except ValueError:
            idx = None
        self.accesses.append(_WrapperAccess(key_node.id, idx, op))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # nested helper scope is separate
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        key_node = _call_key_node(node, self.aliases)
        if key_node is not None:
            self._record(key_node, "read")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_environ(node.value, self.aliases):
            op = "write" if isinstance(node.ctx, ast.Store) else "read"
            self._record(node.slice, op)
        self.generic_visit(node)


def _discover_wrappers(tree: ast.AST, aliases: _Aliases) -> dict[str, _WrapperSpec]:
    wrappers: dict[str, _WrapperSpec] = {}
    body = getattr(tree, "body", ())
    for node in body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        positional, params = _function_params(node)
        probe = _WrapperProbe(params, positional, aliases)
        for stmt in node.body:
            probe.visit(stmt)
        if probe.accesses:
            wrappers[node.name] = _WrapperSpec(node.name, tuple(probe.accesses))
    return wrappers


def _call_argument(node: ast.Call, spec: _WrapperAccess) -> ast.AST | None:
    if spec.positional_index is not None and spec.positional_index < len(node.args):
        return node.args[spec.positional_index]
    for kw in node.keywords:
        if kw.arg == spec.param_name:
            return kw.value
    return None


class _Scanner(ast.NodeVisitor):
    def __init__(
        self,
        rel: str,
        aliases: _Aliases,
        wrappers: dict[str, _WrapperSpec],
    ) -> None:
        self.rel = rel
        self.aliases = aliases
        self.wrappers = wrappers
        self.scope: list[str] = []
        self.items: list[EnvAccess] = []
        self.parents: dict[ast.AST, ast.AST] = {}

    def prepare(self, tree: ast.AST) -> None:
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[child] = parent

    def _scope(self) -> str:
        return "/".join(self.scope) if self.scope else "<module>"

    def _add(
        self,
        node: ast.AST,
        op: str,
        key_node: ast.AST | None,
        *,
        origin: str = "direct",
        explicit_key: str | None = None,
        explicit_hint: str = "",
    ) -> None:
        if explicit_key is None:
            key, expr, hint = _key_info(key_node)
        else:
            key = explicit_key
            expr = _safe_unparse(key_node)
            hint = explicit_hint
        self.items.append(
            EnvAccess(
                self.rel,
                self._scope(),
                op,
                key,
                not self.scope,
                origin=origin,
                key_expr=expr,
                class_hint=hint,
            )
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

    def _project_wrapper_call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name):
            return
        wrapper = self.wrappers.get(node.func.id)
        if wrapper is None:
            return
        for access in wrapper.accesses:
            arg = _call_argument(node, access)
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self._add(
                    node,
                    access.op,
                    arg,
                    origin="literal_helper",
                    explicit_key=arg.value,
                )
                continue
            if arg is None:
                continue
            _key, _expr, hint = _key_info(arg)
            if hint == "dynamic_secret":
                self._add(
                    node,
                    access.op,
                    arg,
                    origin="dynamic_helper",
                    explicit_key="<dynamic>",
                    explicit_hint=hint,
                )

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        key_node = _call_key_node(node, self.aliases)
        if key_node is not None:
            self._add(node, "read", key_node)
        elif isinstance(func, ast.Attribute) and _is_environ(func.value, self.aliases):
            # items/copy/keys/pop/setdefault/etc expose or mutate the environment in
            # shapes that are not a simple one-key read. Keep the historical bulk
            # classification unless/until that API gets its own explicit contract.
            self._add(node, f"bulk:{func.attr}", None, explicit_key="<all>")
        self._project_wrapper_call(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_environ(node.value, self.aliases):
            op = "write" if isinstance(node.ctx, ast.Store) else "read"
            self._add(node, op, node.slice)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if _is_environ(node, self.aliases):
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
                self._add(node, "bulk:raw", None, explicit_key="<all>")
        self.generic_visit(node)


def scan_tree(root: Path) -> list[EnvAccess]:
    items: list[EnvAccess] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        aliases = _collect_aliases(tree)
        wrappers = _discover_wrappers(tree, aliases)
        scanner = _Scanner(rel, aliases, wrappers)
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


def _key_inventory(items: list[EnvAccess]) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    reads: Counter[str] = Counter()
    writes: Counter[str] = Counter()
    module_reads: Counter[str] = Counter()
    files: dict[str, set[str]] = defaultdict(set)
    classes: dict[str, set[str]] = defaultdict(set)
    for item in items:
        if item.op == "write":
            writes[item.key] += 1
        else:
            reads[item.key] += 1
        if item.module_import and item.op != "write":
            module_reads[item.key] += 1
        files[item.key].add(item.file)
        classes[item.key].add(item.access_class)

    all_keys = set(reads) | set(writes) | set(module_reads) | set(files)
    keys: dict[str, dict[str, Any]] = {}
    class_pairs: set[tuple[str, str]] = set()
    for key in sorted(all_keys):
        key_classes = sorted(classes[key]) or [classify_key(key)]
        for cls in key_classes:
            class_pairs.add((key, cls))
        keys[key] = {
            "class": key_classes[0] if len(key_classes) == 1 else "mixed",
            "classes": key_classes,
            "reads": reads[key],
            "writes": writes[key],
            "module_import_reads": module_reads[key],
            "files": sorted(files[key]),
        }
    class_counts = Counter(cls for _key, cls in class_pairs)
    return keys, dict(sorted(class_counts.items()))


def build_inventory(items: list[EnvAccess]) -> dict[str, Any]:
    direct = [item for item in items if item.origin == "direct"]
    literal_helpers = [item for item in items if item.origin == "literal_helper"]
    dynamic_helpers = [item for item in items if item.origin == "dynamic_helper"]
    helper_items = [*literal_helpers, *dynamic_helpers]

    direct_signatures = Counter(item.signature for item in direct)
    helper_signatures = Counter(item.signature for item in helper_items)
    module_signatures = Counter(item.signature for item in items if item.module_import)
    direct_keys, direct_class_keys = _key_inventory(direct)
    helper_keys, helper_class_keys = _key_inventory(helper_items)
    access_classes = Counter(item.access_class for item in items)
    dynamic_secret_signatures = sorted(
        {item.signature for item in items if item.access_class == "dynamic_secret"}
    )

    module_direct = sum(item.module_import for item in direct)
    module_helper = sum(item.module_import for item in helper_items)
    return {
        "schema_version": 2,
        # Backward-compatible physical/direct metric, now alias-aware.
        "access_count": len(direct),
        "direct_access_count": len(direct),
        "literal_helper_access_count": len(literal_helpers),
        "dynamic_helper_access_count": len(dynamic_helpers),
        "effective_access_count": len(items),
        "unique_key_count": len(direct_keys),
        "helper_unique_key_count": len(helper_keys),
        "file_count": len({item.file for item in direct}),
        "effective_file_count": len({item.file for item in items}),
        # v2 authoritative import-time truth includes projected local wrappers.
        "module_import_access_count": module_direct + module_helper,
        "module_import_direct_access_count": module_direct,
        "module_import_helper_access_count": module_helper,
        "class_key_counts": direct_class_keys,
        "helper_class_key_counts": helper_class_keys,
        "access_class_counts": dict(sorted(access_classes.items())),
        "keys": direct_keys,
        "helper_keys": helper_keys,
        # Historical name remains the direct physical ratchet.
        "signature_counts": dict(sorted(direct_signatures.items())),
        "helper_signature_counts": dict(sorted(helper_signatures.items())),
        "module_import_signature_counts": dict(sorted(module_signatures.items())),
        "dynamic_secret_signatures": dynamic_secret_signatures,
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
