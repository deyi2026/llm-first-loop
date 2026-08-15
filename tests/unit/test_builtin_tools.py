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


def test_web_fetch_success(monkeypatch):
    # 本测试聚焦成功路径（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    tool = WebFetchTool()
    # P0-2 后 httpx 通道收敛到 _request（手动重定向循环）；mock 该边界保持行为断言不变
    with mock.patch.object(tool, "_request", return_value=_FakeResponse(200, "<html>Hello Page</html>")):
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


def test_web_fetch_http_error(monkeypatch):
    # 本测试聚焦 HTTP 错误路径（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    tool = WebFetchTool()
    with mock.patch.object(tool, "_curl_fetch", return_value=None), mock.patch.object(
        tool, "_request", return_value=_FakeResponse(404, reason_phrase="Not Found")
    ):
        r = tool.execute(url="https://example.com/missing")
    assert r.status == ToolResultStatus.FAILURE
    assert "404" in r.content


def test_web_fetch_timeout(monkeypatch):
    # 本测试聚焦超时（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    tool = WebFetchTool()
    with mock.patch.object(tool, "_curl_fetch", return_value=None), mock.patch.object(
        tool, "_request", side_effect=__import__("httpx").TimeoutException("timeout")
    ):
        r = tool.execute(url="https://example.com")
    assert r.status == ToolResultStatus.TIMEOUT


def test_web_fetch_timeout_config(tmp_path, monkeypatch):
    """M18 AA8: 工具内超时读配置值（构造注入）+ 文案动态化（默认 30 兜底）."""
    # 本测试聚焦超时配置（非 SSRF）——关闭内网拦截避免测试环境 DNS 干扰
    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    # 默认兜底 30
    t_default = WebFetchTool()
    assert t_default._timeout_s == 30.0
    with mock.patch.object(t_default, "_curl_fetch", return_value=None), mock.patch.object(
        t_default, "_request", side_effect=__import__("httpx").TimeoutException("timeout")
    ):
        r = t_default.execute(url="https://example.com")
    assert "30s" in r.content and "curl 回退亦失败" in r.content
    # 配置注入 45
    t45 = WebFetchTool(timeout_s=45)
    assert t45._timeout_s == 45.0
    with mock.patch.object(t45, "_curl_fetch", return_value=None), mock.patch.object(
        t45, "_request", side_effect=__import__("httpx").TimeoutException("timeout")
    ):
        r45 = t45.execute(url="https://example.com")
    assert "45s" in r45.content
    # 传入的 httpx.Client 超时用配置值（直接构造验证 Client(timeout=...)）
    with mock.patch.object(t45, "_curl_fetch", return_value=None), mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.stream.side_effect = __import__(
            "httpx"
        ).TimeoutException("t")
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


# ── HARNESS-03: web_fetch SSRF 内网拦截 ──


def test_web_fetch_blocks_private_ip(monkeypatch):
    """私网/链路本地地址 → BLOCKED（含云元数据 169.254.169.254）."""
    from llm_loop.tools.builtin.web_fetch import WebFetchTool

    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "1")
    tool = WebFetchTool()
    for url in (
        "http://127.0.0.1:8080/admin",
        "http://192.168.1.1/config",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://172.16.0.1/",
    ):
        r = tool.execute(url=url)
        assert r.status.value == "blocked", f"{url} 应被拦截"
        assert "内网拦截" in r.content


def test_web_fetch_blocks_private_domain(monkeypatch):
    """域名解析到私网（如 localhost 主机名）→ 拦截."""
    from llm_loop.tools.builtin.web_fetch import WebFetchTool

    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "1")
    tool = WebFetchTool()
    r = tool.execute(url="http://localhost:8080/admin")
    assert r.status.value == "blocked"
    assert "内网拦截" in r.content


def test_web_fetch_block_switch_off(monkeypatch):
    """WEB_FETCH_BLOCK_PRIVATE=0 → 不拦截（如实放行到请求阶段）."""
    from llm_loop.tools.builtin.web_fetch import WebFetchTool

    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "0")
    tool = WebFetchTool()
    r = tool.execute(url="http://127.0.0.1:9/x")  # 端口 9 无服务 → 网络错误而非拦截
    assert r.status.value in ("failure", "error")
    assert "内网拦截" not in r.content


def test_web_fetch_public_url_not_blocked(monkeypatch):
    """公网地址正常放行（判定函数返回空）."""
    from llm_loop.tools.builtin.web_fetch import _blocked_private_url

    monkeypatch.setenv("WEB_FETCH_BLOCK_PRIVATE", "1")
    # 公网 IP 字面量放行（域名测试受沙箱 DNS 劫持到 198.18/15 测试段影响——该段本身应拦截）
    assert _blocked_private_url("http://8.8.8.8/path") == ""
    assert _blocked_private_url("https://1.1.1.1/") == ""
