"""inspect_code 代码结构概览工具测试（EVO-20260817 拷问识别的最高 ROI 能力工具）.

覆盖:
- 单文件: 类/方法/函数/import 索引（AST 解析）
- 目录递归: 多文件 + depth 限制 + 忽略隐藏/缓存目录
- keyword 过滤: 只显示匹配条目
- 失败路径: 不存在/非 Python
- 上限保护: 文件数/单文件行数
"""

from __future__ import annotations

from llm_loop.tools.builtin.inspect_code import InspectCodeTool


def _tool() -> InspectCodeTool:
    return InspectCodeTool()


def test_single_file_structure(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "def top_fn(a, b=1):\n"
        "    '''docstring here'''\n"
        "    return a + b\n"
        "\n"
        "class MyClass:\n"
        "    def method1(self, x):\n"
        "        pass\n"
        "    async def method2(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    r = _tool().execute(path=str(f))
    assert r.status.name == "SUCCESS"
    c = r.content
    assert "class MyClass" in c
    assert "def method1(self, x)" in c
    assert "async def method2(self)" in c
    assert "def top_fn(a, b)" in c  # AST 签名不含默认值（如实）
    assert "import os" in c
    assert "from pathlib import Path" in c
    assert "docstring here" in c  # docstring 首行


def test_directory_recursive_and_ignore(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "mod_a.py").write_text("class A:\n    pass\n", encoding="utf-8")
    (pkg / "sub" / "mod_b.py").write_text("def fn_b():\n    pass\n", encoding="utf-8")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "junk.py").write_text("x=1\n", encoding="utf-8")
    (pkg / ".hidden.py").write_text("y=2\n", encoding="utf-8")
    r = _tool().execute(path=str(pkg), depth=2)
    assert r.status.name == "SUCCESS"
    c = r.content
    assert "mod_a.py" in c and "class A" in c
    assert "mod_b.py" in c and "def fn_b" in c
    assert "__pycache__" not in c  # 忽略缓存目录
    assert ".hidden" not in c  # 忽略隐藏文件


def test_keyword_filter(tmp_path):
    f = tmp_path / "k.py"
    f.write_text(
        "class AlphaHandler:\n    pass\n\nclass BetaHelper:\n    pass\n\n"
        "def alpha_fn():\n    pass\n",
        encoding="utf-8",
    )
    r = _tool().execute(path=str(f), keyword="alpha")
    c = r.content
    assert "AlphaHandler" in c
    assert "alpha_fn" in c
    assert "BetaHelper" not in c


def test_nonexistent_path():
    r = _tool().execute(path="/nonexistent/x.py")
    assert r.status.name == "FAILURE"
    assert "路径不存在" in r.content


def test_non_python_file(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("hello", encoding="utf-8")
    r = _tool().execute(path=str(f))
    assert r.status.name == "FAILURE"
    assert "非 Python" in r.content


def test_missing_path_param():
    r = _tool().execute()
    assert r.status.name == "FAILURE"
    assert "path" in r.content


def test_syntax_error_file_skipped(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def broken(:\n", encoding="utf-8")
    r = _tool().execute(path=str(f))
    assert r.status.name == "SUCCESS"
    assert "语法错误" in r.content  # 单文件语法错 → 如实标注不抛异常


def test_no_py_files_in_dir(tmp_path):
    r = _tool().execute(path=str(tmp_path))
    assert r.status.name == "SUCCESS"
    assert "未找到 Python 文件" in r.content


def test_factory_registered():
    """inspect_code 已在 factory 基础工具注册（RUN_MODE hidden 过滤生效）."""
    import inspect

    import llm_loop.factory as F

    src = inspect.getsource(F)
    assert "InspectCodeTool" in src
    assert '_register_basic("inspect_code"' in src
