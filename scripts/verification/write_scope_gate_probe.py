"""write_scope 写侧闸的对抗探针（可复跑；exit 0 = 闸成立）。

用途：核实「`file_service.edit()` 是否真的受 write_scope 约束」——这类断言容易被
"看起来在工作"骗过（宽松解析、只拦一半、返回 None 当放行）。本探针只测**行为**：
正控制（范围内必须放行）+ 各类应拦输入（越界必须拒绝且**字节不变**）+ 旧行为不变。

复跑：`.venv/bin/python scripts/verification/write_scope_gate_probe.py`
（工作目录 = 仓库根；脚本自建临时目录并在结束时清理）

对照测试套件：tests/test_write_scope_enforcement.py、tests/test_write_scope_spawn.py
本探针不替代它们——它们覆盖面更广；本探针是**独立第二来源**，用于交叉验证。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "src")
from llm_loop.core.write_scope import parse_write_scope, write_scope_audit_reset  # noqa: E402
from llm_loop.workspace.artifacts import WorkspaceArtifactStore  # noqa: E402
from llm_loop.workspace.file_effects import FileArtifactProvenance  # noqa: E402
from llm_loop.workspace.file_service import FileService, FileServiceError  # noqa: E402

ROOT = Path(".tmp-write-scope-probe").resolve()
RESULTS: list[tuple[str, bool, str]] = []


def case(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail else ""))


def expect_reject(name: str, path: Path, scope, old: str, new: str, ws: Path, svc) -> None:
    write_scope_audit_reset()
    before = path.read_bytes() if path.exists() else None
    try:
        svc.edit(path=path, old_string=old, new_string=new, workspace_scope=str(ws), write_scope=scope)
    except FileServiceError as exc:
        after = path.read_bytes() if path.exists() else None
        case(name, exc.error_type == "write_scope_violation" and after == before,
             f"error_type={exc.error_type} bytes_unchanged={after == before}")
        return
    case(name, False, "NO EXCEPTION (闸未拦)")


def main() -> int:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ws = ROOT / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "other").mkdir(parents=True)
    src_file = ws / "src" / "a.py"
    src_file.write_bytes(b"x = 1\n")
    other_file = ws / "other" / "x.py"
    other_file.write_bytes(b"secret = 1\n")
    outside = ROOT / "outside.py"
    outside.write_bytes(b"secret = 1\n")
    link = ws / "src" / "link.py"
    os.symlink(outside, link)

    svc = FileService(artifact_store=WorkspaceArtifactStore(ROOT / "data"))
    allow_src = parse_write_scope({"paths": ["src/**"], "mode": "allow"})

    # A 正控制：范围内写必须成功（防"一律拒绝"式假闸）
    r = svc.edit(path=src_file, old_string="x = 1", new_string="x = 2",
                 workspace_scope=str(ws), write_scope=allow_src)
    case("A 正控制 allow src/** → src/a.py 写入成功",
         r.applied is True and src_file.read_bytes() == b"x = 2\n",
         f"applied={r.applied}")

    expect_reject("B 应拦 allow src/** → other/x.py", other_file, allow_src,
                  "secret = 1", "pwned", ws, svc)
    expect_reject("C 应拦 paths=[] 只读子代理", src_file,
                  parse_write_scope({"paths": [], "mode": "allow"}), "x = 2", "x = 3", ws, svc)
    expect_reject("D 应拦 symlink 逃逸", link, allow_src, "secret = 1", "pwned", ws, svc)
    expect_reject("E 应拦 .. 穿越", ws / "other" / ".." / "other" / "x.py", allow_src,
                  "secret = 1", "pwned", ws, svc)

    # F 旧行为不变：无 scope 时维持原语义（不得因引入闸而破坏存量调用）
    r = svc.edit(path=other_file, old_string="secret = 1", new_string="secret = 2",
                 workspace_scope=str(ws), write_scope=None)
    case("F 旧行为不变 write_scope=None → 允许写",
         r.applied is True and other_file.read_bytes() == b"secret = 2\n", f"applied={r.applied}")

    expect_reject("G 应拦 mode=deny paths=[other/**]", other_file,
                  parse_write_scope({"paths": ["other/**"], "mode": "deny"}),
                  "secret = 2", "pwned", ws, svc)

    # H 读侧同闸：observe 越界读必须被同一错误类型拒绝
    prov = FileArtifactProvenance(workspace_scope=str(ws), owner_session_id="s1", operation_id="op1")
    write_scope_audit_reset()
    try:
        svc.observe(path=other_file, workspace_scope=str(ws), provenance=prov, write_scope=allow_src)
        case("H 应拦 observe 越界读", False, "NO EXCEPTION")
    except FileServiceError as exc:
        case("H 应拦 observe 越界读", exc.error_type == "write_scope_violation",
             f"error_type={exc.error_type}")

    leftovers = [str(p) for p in ws.rglob("*.tmp")]
    case("I 拒绝后无半成品文件", not leftovers, f"leftovers={leftovers}")

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL={len(RESULTS)} FAILED={len(failed)} {failed}")
    shutil.rmtree(ROOT, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
