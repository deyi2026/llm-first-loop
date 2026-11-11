"""EVO-20261111-8c5b88df：切片内机械修复的机械判据（仅注解/纯格式）。

背景（REPORT-20261111 §3#7/§4④）：审查-树强绑定下，一次 4 行 pyright 类型
收窄（不改语义/控制流/签名）也会触发整轮全新审查。本模块把"这次 diff 是否
纯机械修复"变成**程序可判**的结论，供审查闸自动预检（narrow re-review 的
任务书分段），无法判定一律 not mechanical（fail-closed，走全新审查轮）。

机械类别（互斥，按严格度递减）：
- ``format_only``——AST 完全相等（仅排版/空白/括号差异，连注解都没变）；
- ``annotation_only``——剥离全部注解子树后 AST 相等（仅类型注解差异：
  新增注解、Any 收窄等。注解不改变 Python 运行时语义）。

其余一切（控制流、字面量、签名参数、新增/删除语句、import、docstring、
非 .py 文件）都判 not mechanical。
"""
from __future__ import annotations

import ast
import copy
import subprocess
from pathlib import Path

__all__ = ["assess_mechanical_fix", "strip_annotations"]



class _AnnStripper(ast.NodeTransformer):
    """注解消除归一（原地改写树副本）。

    - 函数参数注解（posonly/args/kwonly/vararg/kwarg）与 returns 置 None；
    - ``x: T = v``（AnnAssign 有值）降级为 ``x = v``（Assign）——二者运行时
      语义相同（赋值），归一后 dump 相等；
    - ``x: T``（AnnAssign 无值，纯声明）整条删除——不产生任何运行时效果
      （仅 __annotations__ 注解域），两侧各自删除后剩余语句序列一致。
    """

    def _strip_args(self, node: ast.arguments) -> ast.arguments:
        for arg in [
            *node.posonlyargs, *node.args, *node.kwonlyargs,
            *([node.vararg] if node.vararg else []),
            *([node.kwarg] if node.kwarg else []),
        ]:
            arg.annotation = None
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.generic_visit(node)
        node.returns = None
        node.args = self._strip_args(node.args)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self.generic_visit(node)
        node.returns = None
        node.args = self._strip_args(node.args)
        return node

    def visit_Lambda(self, node: ast.Lambda) -> ast.AST:
        self.generic_visit(node)
        node.args = self._strip_args(node.args)
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        self.generic_visit(node)
        if node.value is None:
            return None  # 纯声明：删除（两侧各自删除后序列一致）
        return ast.Assign(
            targets=[node.target], value=node.value, lineno=getattr(node, "lineno", 1)
        )


def strip_annotations(tree: ast.AST) -> ast.AST:
    """把 AST 归一为「无注解形态」（原地修改，建议传 deepcopy）。

    覆盖位置：函数参数注解（含 lambda）、函数 returns、AnnAssign。
    归一后两树 dump 相等 ⇒ 差异仅在注解（新增/收窄/删除注解均不影响运行时语义）。
    """
    return _AnnStripper().visit(tree)


def _diff_paths(repo: Path, old: str, new: str) -> list[str] | None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", old, new],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return None
    return sorted(line for line in proc.stdout.splitlines() if line.strip())


def _blob(repo: Path, sha: str, path: str) -> str | None:
    """二进制取 blob 后严格 UTF-8 解码（非 UTF-8 抛 UnicodeDecodeError，
    调用方按 fail-closed 处理——text 模式会静默替换坏字节，不可接受）。"""
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{sha}:{path}"],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="strict")


_BUILTIN_TYPE_NAMES = frozenset(
    {"int", "str", "float", "bool", "bytes", "complex", "list", "dict", "set",
     "tuple", "frozenset", "type", "object", "None"}
)
_SAFE_ANN_NODES = (
    ast.Name, ast.Attribute, ast.Subscript, ast.Constant, ast.Tuple, ast.List,
    ast.Load, ast.Store, ast.Del,  # ctx 节点（ast.walk 会遍历到，非可执行结构）
)


def _future_annotations_active(module: ast.Module) -> bool:
    """模块级 ``from __future__ import annotations`` ⇒ 所有注解惰性化为字符串。"""
    for node in module.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(a.name == "annotations" for a in node.names)
        ):
            return True
    return False


def _known_names(stripped_tree: ast.AST) -> set[str]:
    """剥离注解后的树里可解析的名字：所有 Name.id + import 绑定名。

    旧文件的非注解代码在旧版本已成功求值——这些名字在 import/def 时已知
    可解析（ruff/运行已验证过）。新注解只引用这些名字或内建类型名时，
    求值不会新增 NameError 风险。
    """
    names: set[str] = set()
    for node in ast.walk(stripped_tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


def _annotation_subtrees(tree: ast.AST) -> list[ast.AST]:
    subs: list[ast.AST] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.returns is not None
        ):
            subs.append(node.returns)
        if isinstance(node, ast.arguments):
            for arg in [
                *node.posonlyargs, *node.args, *node.kwonlyargs,
                *([node.vararg] if node.vararg else []),
                *([node.kwarg] if node.kwarg else []),
            ]:
                if arg.annotation is not None:
                    subs.append(arg.annotation)
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            subs.append(node.annotation)
    return subs


def _annotation_eagerly_safe(ann: ast.AST, known: set[str]) -> bool:
    """注解子树在急切求值（无 future import）下的安全判定（fail-closed）。

    只允许不可执行结构（Name/Attribute/Subscript/Constant/Tuple/List）；
    任何 Call/BinOp/Lambda/推导/JoinedStr 等可执行结构立即判不安全。
    裸 Name 必须是内建类型名或旧代码已知可解析的名字（防 NameError）。
    """
    for node in ast.walk(ann):
        if not isinstance(node, _SAFE_ANN_NODES):
            return False
        if isinstance(node, ast.Name) and node.id not in known:
            return False
    return True


def _classify(old_src: str, new_src: str) -> str:
    """返回 format_only / annotation_only / semantic（fail-closed 由调用方处理异常）。

    annotation_only 额外过"急切求值安全闸"（2026-11-11 审查 P1）：无
    ``from __future__ import annotations`` 时注解在 import/def 时被求值——
    新注解必须是不可执行结构且只引用已知名字；否则判
    ``eager_annotation_risk``（not mechanical）。有 future import 时全部
    注解惰性化，任意注解变化安全。
    """
    old_tree = ast.parse(old_src)
    new_tree = ast.parse(new_src)
    if ast.dump(old_tree) == ast.dump(new_tree):
        return "format_only"
    norm_old = strip_annotations(copy.deepcopy(old_tree))
    norm_new = strip_annotations(copy.deepcopy(new_tree))
    if ast.dump(norm_old) != ast.dump(norm_new):
        return "semantic"
    if _future_annotations_active(new_tree):
        return "annotation_only"
    known = _known_names(norm_old) | _BUILTIN_TYPE_NAMES
    for ann in _annotation_subtrees(new_tree):
        if not _annotation_eagerly_safe(ann, known):
            return "eager_annotation_risk"
    return "annotation_only"


def assess_mechanical_fix(
    repo_path: str | Path,
    *,
    old_sha: str,
    new_sha: str,
    allowed_paths: list[str] | None = None,
) -> dict:
    """判定 ``old_sha..new_sha`` 的 diff 是否为切片内纯机械修复。

    判据（全部机检，fail-closed）：
    1. diff 触碰的每个文件都是 ``.py`` 且能从 git 取到新旧两端内容；
    2. 每个文件解析成功且分类为 format_only 或 annotation_only；
    3. 给定 ``allowed_paths``（切片声明）时，触碰路径不得越出切片。

    返回::

        {
          "mechanical": bool,
          "category": "format_only"|"annotation_only"|"",   # mixed 时 "annotation_only"
          "reason": "",  # not mechanical 时的机检原因
          "changed_paths": [...],
          "per_file": {path: "format_only"|"annotation_only"},
        }

    任何判不了（git 失败、SyntaxError、非 .py、越出切片、语义变化）⇒
    ``mechanical=False``，调用方走全新审查轮。
    """
    repo = Path(repo_path)
    paths = _diff_paths(repo, old_sha, new_sha)
    if paths is None:
        return {
            "mechanical": False, "category": "", "reason": "fail_closed:git_diff_failed",
            "changed_paths": [], "per_file": {},
        }
    if not paths:
        return {
            "mechanical": False, "category": "", "reason": "no_change",
            "changed_paths": [], "per_file": {},
        }
    non_py = [p for p in paths if not p.endswith(".py")]
    if non_py:
        return {
            "mechanical": False, "category": "",
            "reason": f"non_python:{','.join(non_py)}",
            "changed_paths": paths, "per_file": {},
        }
    if allowed_paths is not None:
        outside = [p for p in paths if p not in set(allowed_paths)]
        if outside:
            return {
                "mechanical": False, "category": "",
                "reason": f"outside_slice:{','.join(outside)}",
                "changed_paths": paths, "per_file": {},
            }
    per_file: dict[str, str] = {}
    for path in paths:
        old_src = _blob(repo, old_sha, path)
        new_src = _blob(repo, new_sha, path)
        if old_src is None or new_src is None:
            return {
                "mechanical": False, "category": "",
                "reason": f"fail_closed:blob_unavailable:{path}",
                "changed_paths": paths, "per_file": {},
            }
        try:
            category = _classify(old_src, new_src)
        except SyntaxError:
            return {
                "mechanical": False, "category": "",
                "reason": f"fail_closed:syntax_error:{path}",
                "changed_paths": paths, "per_file": {},
            }
        except UnicodeDecodeError:
            return {
                "mechanical": False, "category": "",
                "reason": f"fail_closed:decode_error:{path}",
                "changed_paths": paths, "per_file": {},
            }
        if category == "semantic":
            return {
                "mechanical": False, "category": "",
                "reason": f"semantic_change:{path}",
                "changed_paths": paths, "per_file": {},
            }
        if category == "eager_annotation_risk":
            return {
                "mechanical": False, "category": "",
                "reason": f"eager_annotation_risk:{path}",
                "changed_paths": paths, "per_file": {},
            }
        per_file[path] = category
    overall = "format_only" if set(per_file.values()) == {"format_only"} else "annotation_only"
    return {
        "mechanical": True, "category": overall, "reason": "",
        "changed_paths": paths, "per_file": per_file,
    }
