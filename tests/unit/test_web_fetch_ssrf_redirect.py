"""P0-2/P0-3(2026-08-15): web_fetch SSRF 深化（审计发现 #1/#2）.

#1 重定向跟随绕过：原实现对 3xx 目标不再做内网校验（httpx follow_redirects=True
与 curl -L 都自动跟随）——公开 URL 302 跳云元数据 169.254.169.254 即泄凭证。
修复：手动重定向循环，每一跳重新校验（含 DNS 解析判定），上限 5 跳。

#2 DNS rebinding TOCTOU：校验时解析的 IP 与连接时实际对端可能不同。
修复（混合方案）：
- curl 通道：--resolve 钉住已校验 IP（预连接钉扎，SNI/证书校验不受损）
- httpx 通道：连接后读取实际对端 IP（network_stream server_addr）复核，
  命中私网即丢弃连接（如实标注：GET 已发出，防的是数据回读；更强隔离见 curl 通道）

测试全程 mock 网络层（httpx.Client / subprocess.run / getaddrinfo），不触网。
"""

from __future__ import annotations

import subprocess
from unittest import mock

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.web_fetch import WebFetchTool

PUBLIC_IP = "93.184.216.34"  # example.com 历史公网 IP（字面量判定，无需 DNS）


class _FakeStreamResp:
    """httpx stream 响应替身（__enter__/__exit__/read/extensions）."""

    def __init__(self, status: int, body: str = "", headers: dict | None = None,
                 extensions: dict | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self.extensions = extensions or {}
        self.content = body.encode("utf-8")
        self.text = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self.content


class _ScriptedClient:
    """按 URL 脚本化的 httpx.Client 替身（stream 接口）."""

    def __init__(self, script: dict[str, object]) -> None:
        self._script = script
        self.requests: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def stream(self, method: str, url: str, headers: dict | None = None):
        self.requests.append(url)
        item = self._script.get(url)
        if item is None:
            raise RuntimeError(f"脚本外 URL: {url}")
        if isinstance(item, Exception):
            raise item
        return item


def _make_tool(script: dict[str, object]):
    """装配：httpx.Client 替换为脚本替身；curl 通道默认置失败（聚焦 httpx 路径）."""
    tool = WebFetchTool()
    patches = [
        mock.patch("httpx.Client", return_value=_ScriptedClient(script)),
        mock.patch.object(tool, "_curl_fetch", return_value=None),
    ]
    return tool, patches


# ── P0-2: 重定向逐跳校验 ──
def test_redirect_to_private_ip_blocked():
    """公开 URL 302 → 云元数据地址：第二跳命中内网，BLOCKED（修复前自动跟随泄漏）."""
    script = {
        f"https://{PUBLIC_IP}/page": _FakeStreamResp(
            302, headers={"location": "http://169.254.169.254/latest/meta-data"}
        ),
    }
    tool, patches = _make_tool(script)
    with patches[0], patches[1]:
        r = tool.execute(url=f"https://{PUBLIC_IP}/page")
    assert r.status == ToolResultStatus.BLOCKED
    assert "内网拦截" in r.content
    assert "169.254.169.254" in r.content


def test_redirect_to_loopback_blocked():
    script = {
        f"https://{PUBLIC_IP}/x": _FakeStreamResp(
            301, headers={"location": "http://127.0.0.1:8080/admin"}
        ),
    }
    tool, patches = _make_tool(script)
    with patches[0], patches[1]:
        r = tool.execute(url=f"https://{PUBLIC_IP}/x")
    assert r.status == ToolResultStatus.BLOCKED
    assert "127.0.0.1" in r.content


def test_redirect_chain_over_limit_fails():
    """5 跳上限：公网地址互跳 6 次 → 如实失败（防无限循环/资源耗尽）."""
    a, b = f"https://{PUBLIC_IP}/a", f"https://{PUBLIC_IP}/b"
    script = {
        a: _FakeStreamResp(302, headers={"location": b}),
        b: _FakeStreamResp(302, headers={"location": a}),
    }
    tool, patches = _make_tool(script)
    with patches[0], patches[1]:
        r = tool.execute(url=a)
    assert r.status == ToolResultStatus.FAILURE
    assert "重定向" in r.content


def test_redirect_public_to_public_succeeds():
    """公开 → 公开一跳正常跟随（重定向功能不残废，只拦内网目标）."""
    first, final = f"https://{PUBLIC_IP}/old", f"https://{PUBLIC_IP}/new"
    script = {
        first: _FakeStreamResp(302, headers={"location": final}),
        final: _FakeStreamResp(200, "<html><p>最终页内容充足，超过二十个字符的正文用于通过提取门槛校验。</p></html>"),
    }
    tool, patches = _make_tool(script)
    with patches[0], patches[1]:
        r = tool.execute(url=first)
    assert r.status == ToolResultStatus.SUCCESS
    assert "最终页内容" in r.content


# ── P0-3: httpx 连接后对端 IP 复核（DNS rebinding）──
def test_post_connect_private_peer_discarded():
    """URL 校验通过（公网字面量），但实际连接落在私网对端（rebinding 模拟）→ 丢弃."""
    fake_stream = mock.MagicMock()
    fake_stream.get_extra_info.return_value = ("10.0.0.8", 443)
    script = {
        f"https://{PUBLIC_IP}/ok": _FakeStreamResp(
            200, "content", extensions={"network_stream": fake_stream}
        ),
    }
    tool, patches = _make_tool(script)
    with patches[0], patches[1]:
        r = tool.execute(url=f"https://{PUBLIC_IP}/ok")
    assert r.status == ToolResultStatus.BLOCKED
    assert "10.0.0.8" in r.content


def test_post_connect_public_peer_passes():
    fake_stream = mock.MagicMock()
    fake_stream.get_extra_info.return_value = (PUBLIC_IP, 443)
    script = {
        f"https://{PUBLIC_IP}/ok": _FakeStreamResp(
            200,
            "<html><p>对端公网，正常放行——内容长度超过二十字符门槛以通过提取。</p></html>",
            extensions={"network_stream": fake_stream},
        ),
    }
    tool, patches = _make_tool(script)
    with patches[0], patches[1]:
        r = tool.execute(url=f"https://{PUBLIC_IP}/ok")
    assert r.status == ToolResultStatus.SUCCESS


# ── P0-3: curl 通道 --resolve 钉 IP + 逐跳校验 ──
def _fake_proc(code: int, body: str = "", redirect: str = "") -> subprocess.CompletedProcess:
    out = body + f"\n{code} {redirect}"
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=out.encode(), stderr=b"")


def test_curl_pins_validated_ip():
    """域名 URL 经 getaddrinfo 校验后，curl --resolve 钉住已校验 IP（防 TOCTOU 二次解析漂移）."""
    tool = WebFetchTool()
    captured: list[list[str]] = []

    def fake_run(argv, **kwargs):
        captured.append(argv)
        return _fake_proc(200, "<html><p>curl 通道内容，长度需超过二十字符门槛以通过提取校验。</p></html>")

    import socket as _socket

    def fake_getaddrinfo(host, port, *a, **k):
        return [(2, 1, 6, "", (PUBLIC_IP, 0))]

    with mock.patch("httpx.Client", side_effect=RuntimeError("force curl")), \
         mock.patch("subprocess.run", side_effect=fake_run), \
         mock.patch.object(_socket, "getaddrinfo", side_effect=fake_getaddrinfo):
        r = tool.execute(url="https://curl-pin.example.com/page")
    assert r.status == ToolResultStatus.SUCCESS
    resolve_args = [a for argv in captured for a in argv if a.startswith("curl-pin.example.com:")]
    assert resolve_args, f"curl 未钉 IP（无 --resolve 参数）: {captured}"
    assert any(PUBLIC_IP in a for a in resolve_args), f"--resolve 未指向已校验 IP: {resolve_args}"


def test_curl_redirect_to_private_blocked():
    """curl 通道第二跳 302 → 回环地址：BLOCKED（修复前 -L 自动跟随泄漏）."""
    tool = WebFetchTool()
    calls: list[str] = []

    def fake_run(argv, **kwargs):
        url = argv[-1]
        calls.append(url)
        if "first" in url:
            return _fake_proc(302, "", "http://127.0.0.1/internal")
        return _fake_proc(200, "不应到达")

    with mock.patch("httpx.Client", side_effect=RuntimeError("force curl")), \
         mock.patch("subprocess.run", side_effect=fake_run):
        r = tool.execute(url=f"https://{PUBLIC_IP}/first")
    assert r.status == ToolResultStatus.BLOCKED
    assert "127.0.0.1" in r.content
    assert not any("internal" in u for u in calls), "BLOCKED 后仍抓取了内网目标"
