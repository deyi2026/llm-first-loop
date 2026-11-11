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
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{sha}:{path}"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _classify(old_src: str, new_src: str) -> str:
    """返回 format_only / annotation_only / semantic（fail-closed 由调用方处理异常）。"""
    old_tree = ast.parse(old_src)
    new_tree = ast.parse(new_src)
    if ast.dump(old_tree) == ast.dump(new_tree):
        return "format_only"
    norm_old = ast.dump(strip_annotations(copy.deepcopy(old_tree)))
    norm_new = ast.dump(strip_annotations(copy.deepcopy(new_tree)))
    if norm_old == norm_new:
        return "annotation_only"
    return "semantic"


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
        if category == "semantic":
            return {
                "mechanical": False, "category": "",
                "reason": f"semantic_change:{path}",
                "changed_paths": paths, "per_file": {},
            }
        per_file[path] = category
    overall = "format_only" if set(per_file.values()) == {"format_only"} else "annotation_only"
    return {
        "mechanical": True, "category": overall, "reason": "",
        "changed_paths": paths, "per_file": per_file,
    }
