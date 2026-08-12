"""单元测试: web_fetch / read_file / execute_command 边界（T18/T20 覆盖补强）."""

from __future__ import annotations

from unittest import mock

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.builtin.web_fetch import WebFetchTool


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", reason_phrase: str = "OK") -> None:
        self.status_code = status_code
        self.text = text
        self.reason_phrase = reason_phrase


def test_web_fetch_success():
    tool = WebFetchTool()
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _FakeResponse(
            200, "<html>Hello Page</html>"
        )
        r = tool.execute(url="https://example.com")
    assert r.status == ToolResultStatus.SUCCESS
    assert "Hello Page" in r.content


def test_web_fetch_invalid_url():
    tool = WebFetchTool()
    r = tool.execute(url="not-a-url")
    assert r.status == ToolResultStatus.FAILURE
    assert "URL 无效" in r.content


def test_web_fetch_missing_url():
    tool = WebFetchTool()
    r = tool.execute()
    assert r.status == ToolResultStatus.FAILURE
    assert "缺少必填参数" in r.content


def test_web_fetch_http_error():
    tool = WebFetchTool()
    with mock.patch.object(tool, "_curl_fetch", return_value=None), mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _FakeResponse(
            404, reason_phrase="Not Found"
        )
        r = tool.execute(url="https://example.com/missing")
    assert r.status == ToolResultStatus.FAILURE
    assert "404" in r.content


def test_web_fetch_timeout():
    tool = WebFetchTool()
    with mock.patch.object(tool, "_curl_fetch", return_value=None), mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = mock.MagicMock(
            side_effect=__import__("httpx").TimeoutException("timeout")
        )
        r = tool.execute(url="https://example.com")
    assert r.status == ToolResultStatus.TIMEOUT


def test_web_fetch_timeout_config(tmp_path):
    """M18 AA8: 工具内超时读配置值（构造注入）+ 文案动态化（默认 30 兜底）."""
    # 默认兜底 30
    t_default = WebFetchTool()
    assert t_default._timeout_s == 30.0
    with mock.patch.object(t_default, "_curl_fetch", return_value=None), mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = mock.MagicMock(
            side_effect=__import__("httpx").TimeoutException("timeout")
        )
        r = t_default.execute(url="https://example.com")
    assert "30s" in r.content and "curl 回退亦失败" in r.content
    # 配置注入 45
    t45 = WebFetchTool(timeout_s=45)
    assert t45._timeout_s == 45.0
    with mock.patch.object(t45, "_curl_fetch", return_value=None), mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = mock.MagicMock(
            side_effect=__import__("httpx").TimeoutException("timeout")
        )
        r45 = t45.execute(url="https://example.com")
    assert "45s" in r45.content
    # 传入的 httpx.Client 超时用配置值（直接构造验证 Client(timeout=...)）
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = mock.MagicMock(
            status_code=200, text="ok", headers={}
        )
        t45.execute(url="https://example.com")
        call_kwargs = client_cls.call_args.kwargs
        assert call_kwargs["timeout"] == 45.0


def test_execute_command_timeout_config():
    """M18 AA8: ExecuteCommandTool 超时读配置值（默认 30 兜底 + 文案动态化）."""
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    t_default = ExecuteCommandTool()
    assert t_default._timeout_s == 30.0
    t45 = ExecuteCommandTool(timeout_s=45)
    assert t45._timeout_s == 45.0
    with mock.patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("c", 45)):
        r = t45.execute(command="sleep 100")
    assert r.status == ToolResultStatus.TIMEOUT
    assert "超过 45s" in r.content


def test_read_file_offset_limit(tmp_path):
    f = tmp_path / "multi.txt"
    f.write_text("\n".join(f"line{i}" for i in range(10)), encoding="utf-8")
    tool = ReadFileTool()
    r = tool.execute(path=str(f), offset=5, limit=3)
    assert r.status == ToolResultStatus.SUCCESS
    assert "line5" in r.content
    assert "line8" not in r.content  # 只读 3 行


def test_read_file_directory(tmp_path):
    tool = ReadFileTool()
    r = tool.execute(path=str(tmp_path))
    assert r.status == ToolResultStatus.FAILURE
    assert "目录" in r.content


def test_read_file_missing(tmp_path):
    tool = ReadFileTool()
    r = tool.execute(path=str(tmp_path / "nope.txt"))
    assert r.status == ToolResultStatus.FAILURE
    assert "不存在" in r.content


def test_read_file_missing_path():
    tool = ReadFileTool()
    r = tool.execute()
    assert r.status == ToolResultStatus.FAILURE
