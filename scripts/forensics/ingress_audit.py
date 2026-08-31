#!/usr/bin/env python3
"""ingress 静态扫描器（tasks 1.2，design A1，spec 5.1.1-1）.

纯 AST 静态扫描全仓生产代码（src/llm_loop）：
- ``Message(role="user", ...)`` 构造点（user 身份写入面）
- ``*.messages.append(...)`` 调用点（会话追加面）
- ``origin_metadata`` 引用点（单一真相源消费面）
- ``"origin_layer"`` 字面量直构造点（绕过真相源的手工构造嫌疑）
- ``engine.run(`` / ``.run_stream(`` 调用方（E1 主入口可达面）

输出 JSON + Markdown 双格式入口清单；每条含 文件:行号锚点 / 写入身份 /
metadata 构造方式 / 可达性判定（可达 / 不可达 / 条件可达）。

离线取证产物，不进运行时热路径（spec 4.1-2）。
用法：python3 scripts/forensics/ingress_audit.py [repo_root] [--out DIR]
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

SCAN_ROOT_REL = "src/llm_loop"

# 可达性判定的已知锚点（语义判定，容忍行号漂移）：(path 后缀, finding kind, 判定)
_REACHABILITY_RULES: list[tuple[str, str, str]] = [
    ("loop/engine.py", "user_role_construct", "可达（E1 主入口：run 内构造并落库）"),
    ("loop/turn_context.py", "user_role_construct", "可达（memory_snapshot 程序层标记落盘）"),
    ("subagent/runner.py", "user_role_construct", "条件可达（spawn_subagent 触发；E2 零 metadata 缺陷点）"),
    ("loop/turn_context.py", "origin_layer_literal", "不可达落盘（never persist 合成视图，仅 gate 计算）"),
    ("injection_labels.py", "origin_layer_literal", "不可达绕过（单一真相源本体构造）"),
]


@dataclass
class Finding:
    kind: str  # user_role_construct / messages_append / origin_metadata_ref / origin_layer_literal / engine_run_caller
    file: str
    line: int
    anchor: str  # 源码行摘录
    identity: str  # 写入身份说明
    metadata_style: str  # metadata 构造方式
    reachability: str  # 可达/不可达/条件可达 + 说明
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "anchor": self.anchor,
            "identity": self.identity,
            "metadata_style": self.metadata_style,
            "reachability": self.reachability,
        }


@dataclass
class AuditReport:
    repo_root: str
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "repo_root": self.repo_root,
            "finding_count": len(self.findings),
            "kinds": sorted({f.kind for f in self.findings}),
            "findings": [f.to_dict() for f in self.findings],
        }


def _is_message_call(node: ast.Call) -> bool:
    name = node.func
    if isinstance(name, ast.Name):
        return name.id == "Message"
    if isinstance(name, ast.Attribute):
        return name.attr == "Message"
    return False


def _kw_role_user(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "role":
            v = kw.value
            if isinstance(v, ast.Constant) and v.value == "user":
                return "user"
            if isinstance(v, ast.Constant):
                return str(v.value)
            return "<dynamic>"
    for arg in call.args:
        # Message("user", ...) 位置参数形态
        if isinstance(arg, ast.Constant) and arg.value == "user":
            return "user"
    return None


def _describe_metadata(call: ast.Call) -> str:
    for kw in call.keywords:
        if kw.arg == "metadata":
            v = kw.value
            if isinstance(v, ast.Call):
                fn = v.func
                fn_name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if fn_name == "origin_metadata":
                    layer = ""
                    if v.args:
                        a = v.args[0]
                        layer = getattr(a, "attr", "") or getattr(a, "id", "") or (
                            getattr(a, "value", "") if isinstance(a, ast.Constant) else ""
                        )
                    kinds = [
                        f"{kw2.arg}={getattr(kw2.value, 'value', '?')}"
                        for kw2 in v.keywords
                        if kw2.arg == "injection_kind"
                    ]
                    return f"origin_metadata({layer}{'，' + '；'.join(kinds) if kinds else ''})"
                return f"调用 {fn_name}(...)"
            if isinstance(v, ast.Dict):
                keys = [
                    getattr(k, "value", "?") if isinstance(k, ast.Constant) else "?"
                    for k in v.keys
                ]
                return "手工 dict{" + ", ".join(keys) + "}"

            return "<表达式>"
    return "无 metadata 字段"


def _reachability_for(rel: str, snippet: str, kind: str = "") -> str:
    for suffix, rule_kind, verdict in _REACHABILITY_RULES:
        if rel.endswith(suffix) and (not rule_kind or rule_kind == kind):
            return verdict
    if "/tests/" in rel or rel.startswith("tests/"):
        return "测试代码（生产不可达）"
    return "条件可达（需人工复核调用链）"


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel: str, lines: list[str], findings: list[Finding]) -> None:
        self.rel = rel
        self.lines = lines
        self.findings = findings

    def _snippet(self, lineno: int) -> str:
        try:
            return self.lines[lineno - 1].strip()
        except IndexError:
            return ""

    def visit_Call(self, node: ast.Call) -> None:
        snippet = self._snippet(node.lineno)
        rel = self.rel

        # 1) Message(role="user") 构造点
        if _is_message_call(node):
            role = _kw_role_user(node)
            if role == "user":
                style = _describe_metadata(node)
                if "origin_metadata" in style:
                    identity = "程序构造，经真相源标记"
                elif "手工" in style or "无 metadata" in style:
                    identity = "程序构造，标记缺失/手工（嫌疑）"
                else:
                    identity = "程序构造"
                self.findings.append(
                    Finding(
                        kind="user_role_construct",
                        file=rel,
                        line=node.lineno,
                        anchor=snippet[:160],
                        identity=identity,
                        metadata_style=style,
                        reachability=_reachability_for(rel, snippet, "user_role_construct"),
                    )
                )

        # 2) *.messages.append 调用点
        fn = node.func
        if (
            isinstance(fn, ast.Attribute)
            and fn.attr == "append"
            and isinstance(fn.value, ast.Attribute)
            and fn.value.attr == "messages"
        ):
            base = fn.value.value
            base_name = getattr(base, "id", None) or getattr(base, "attr", "?")
            self.findings.append(
                Finding(
                    kind="messages_append",
                    file=rel,
                    line=node.lineno,
                    anchor=snippet[:160],
                    identity=f"会话对象 {base_name}.messages 追加",
                    metadata_style="取决于被追加 Message 构造",
                    reachability=_reachability_for(rel, snippet, "messages_append"),
                )
            )

        # 3) origin_metadata 引用点
        if isinstance(fn, ast.Name) and fn.id == "origin_metadata":
            self.findings.append(
                Finding(
                    kind="origin_metadata_ref",
                    file=rel,
                    line=node.lineno,
                    anchor=snippet[:160],
                    identity="单一真相源构造调用",
                    metadata_style=_describe_metadata(node),
                    reachability=_reachability_for(rel, snippet, "engine_run_caller"),
                )
            )

        # 5) engine.run / run_stream 调用方
        if (
            isinstance(fn, ast.Attribute)
            and fn.attr in ("run", "run_stream")
            and isinstance(fn.value, ast.Attribute)
            and fn.value.attr in ("engine", "_engine")
        ) or (
            isinstance(fn, ast.Attribute)
            and fn.attr in ("run", "run_stream")
            and isinstance(fn.value, ast.Name)
            and fn.value.id in ("engine", "_engine", "self")
        ):
            self.findings.append(
                Finding(
                    kind="engine_run_caller",
                    file=rel,
                    line=node.lineno,
                    anchor=snippet[:160],
                    identity="E1 主入口调用方（user_text 信任链）",
                    metadata_style="落盘 metadata 由 engine.run 内部构造",
                    reachability=_reachability_for(rel, snippet, "engine_run_caller"),
                )
            )
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        # 4) "origin_layer" 字面量直构造点
        for k in node.keys:
            if isinstance(k, ast.Constant) and k.value == "origin_layer":
                snippet = self._snippet(node.lineno)
                self.findings.append(
                    Finding(
                        kind="origin_layer_literal",
                        file=self.rel,
                        line=node.lineno,
                        anchor=snippet[:160],
                        identity="手工 origin_layer 字面量构造（绕过真相源嫌疑）",
                        metadata_style="手工 dict 字面量",
                        reachability=_reachability_for(self.rel, snippet, "origin_layer_literal"),
                    )
                )
        self.generic_visit(node)


def audit_ingress_points(repo_root: str | Path = ".") -> AuditReport:
    """扫描 repo_root/src/llm_loop 生产代码，返回入口清单报告。"""
    repo = Path(repo_root)
    report = AuditReport(repo_root=str(repo.resolve()))
    for py in sorted((repo / SCAN_ROOT_REL).rglob("*.py")):
        rel = str(py.relative_to(repo))
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError:
            continue
        lines = py.read_text(encoding="utf-8").splitlines()
        _Visitor(rel, lines, report.findings).visit(tree)
    return report


def write_outputs(report: AuditReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    js = out_dir / "ingress-audit.json"
    md = out_dir / "ingress-audit.md"
    js.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    kind_names = {
        "user_role_construct": "role=user 构造点",
        "messages_append": "messages.append 调用点",
        "origin_metadata_ref": "origin_metadata 引用点",
        "origin_layer_literal": "origin_layer 字面量直构造点",
        "engine_run_caller": "engine.run 调用方",
    }
    rows = ["# ingress 入口审计清单（静态扫描）", "", f"- repo: `{report.repo_root}`", f"- findings: {len(report.findings)}", ""]
    for kind_label in kind_names.values():
        subset = [f for f in report.findings if kind_names.get(f.kind) == kind_label]
        if not subset:
            continue
        rows += [f"## {kind_label}（{len(subset)}）", "", "| 文件:行 | 写入身份 | metadata 构造 | 可达性 |", "|---|---|---|---|"]
        for f in subset:
            rows.append(
                f"| `{f.file}:{f.line}` | {f.identity} | {f.metadata_style} | {f.reachability} |"
            )
        rows.append("")
    md.write_text("\n".join(rows), encoding="utf-8")
    return js, md


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo_root", nargs="?", default=".")
    ap.add_argument("--out", default=None, help="产物目录（缺省 scripts/forensics/out）")
    args = ap.parse_args()
    report = audit_ingress_points(args.repo_root)
    out = Path(args.out) if args.out else Path(args.repo_root) / "scripts/forensics/out"
    js, md = write_outputs(report, out)
    print(f"[ok] {len(report.findings)} findings -> {js} / {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
