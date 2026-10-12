"""present_files 工具回归（DSH deliverables 语义对齐）。

契约：模型显式声明已存在的输出文件为交付物 → Web 会话"出产物"面板可打开/预览。
机械边界：工作区根内、仅普通文件、全有或全无（任一无效即整体 FAILURE）、
只登记事实（大小/修改时间），不复制不改内容。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.run_context import current_workspace_root
from llm_loop.tools.builtin.present_files import PresentFilesTool


def _run(tmp_path: Path, files: object) -> object:
    token = current_workspace_root.set(str(tmp_path.resolve()))
    try:
        return PresentFilesTool().execute(files=files)
    finally:
        current_workspace_root.reset(token)


def test_registers_existing_files_with_facts(tmp_path: Path) -> None:
    doc = tmp_path / "docs" / "SPEC-x.md"
    doc.parent.mkdir()
    doc.write_text("hello spec", encoding="utf-8")

    result = _run(
        tmp_path,
        [{"path": "docs/SPEC-x.md", "description": "优化方案"}, {"path": str(doc)}],
    )

    assert result.status == "success", result.content
    assert "docs/SPEC-x.md" in result.content
    assert "10" in result.content  # size 事实（字节）
    assert "优化方案" in result.content  # description 原样带回


def test_rejects_any_invalid_file_all_or_nothing(tmp_path: Path) -> None:
    good = tmp_path / "a.txt"
    good.write_text("x", encoding="utf-8")

    result = _run(tmp_path, [{"path": "a.txt"}, {"path": "gone.txt"}])

    assert result.status == "failure", result.content
    assert "gone.txt" in result.content


def test_rejects_path_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "dsh-present-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        result = _run(tmp_path, [{"path": str(outside)}])
    finally:
        outside.unlink(missing_ok=True)

    assert result.status == "failure", result.content
    assert "越" in result.content or "工作区" in result.content


def test_rejects_directory(tmp_path: Path) -> None:
    (tmp_path / "adir").mkdir()
    result = _run(tmp_path, [{"path": "adir"}])
    assert result.status == "failure", result.content
    assert "adir" in result.content


def test_rejects_bad_payload_shapes(tmp_path: Path) -> None:
    for bad in (
        None,
        "docs/a.md",
        [],
        [{"description": "缺 path"}],
        [{"path": "  "}],
        [{"path": f"f{i}.txt"} for i in range(21)],  # 超上限
    ):
        result = _run(tmp_path, bad)
        assert result.status == "failure", f"payload={bad!r} 不应被接受"
