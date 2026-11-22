"""cdp_probe：CDP 端点可达性探针工具（EVO-20261121-efa320ab）。

只读探针：发现候选端点 → 探测可达性 → 如实回报。它**不改配置、不启动浏览器、
不放宽既有 browser 工具的显式 opt-in 门禁**；只是把"端点存在吗"这一此前
不可回答的事实变成可回答的事实。
"""

from __future__ import annotations

import time

from llm_loop.browser.cdp_probe import (
    DEFAULT_PROBE_PORTS,
    DEFAULT_TIMEOUT_S,
    MAX_CANDIDATES,
    MAX_EXTRA_PORTS,
    MAX_EXTRA_USER_DATA_DIRS,
    discover_cdp_candidates,
    probe_cdp_endpoint,
)
from llm_loop.core.message import ToolResult, ToolResultStatus

_ENV_HINT = "LFL_BROWSER_PERCEPTION_CDP_URL"
MAX_TIMEOUT_S = 10.0
# 整体探测时限（review P2-2：单请求超时不是整体上界——端点数无界时总耗时可线性膨胀）
TOTAL_TIMEOUT_S = 10.0
_CHROME_POLICY_NOTE = (
    "Chrome 136+ 对默认用户目录禁用 --remote-debugging-port：需以非默认 --user-data-dir "
    "启动才会暴露 CDP 端点（已有登录态的默认配置无法直接开远程调试）。"
)


class CdpProbeTool:
    name = "cdp_probe"
    description = (
        "探测本机 Chrome/Chromium 的 CDP(DevTools) 端点是否可达，只读回元信息（环境诊断，非页面能力）。"
        "何时用: 需要操作用户已打开、已登录的浏览器（头条/后台等）但不知道远程调试端口是否开启、"
        "CDP 端点地址是什么时；browser_perceive/browser_operate 未注册时先自查端点。"
        "何时不用: 需要页面内容或操作（用 browser_perceive/browser_operate）；需要本机文件（用 search_files/read_file）。"
        "输出: 逐端点的可达性、浏览器版本、协议版本、目标计数（**不含**页面标题/URL 等页面内容）"
        "与可直接采用的端点地址。"
        "边界: 只探 loopback；不改任何配置、不启动浏览器、不读页面内容；browser 工具仍需显式设置 "
        f"{_ENV_HINT} 并重启服务后才会注册（本工具不放宽该 opt-in，也不属于 browser 页面能力家族）。"
        f"上界: 整体探测 ≤{TOTAL_TIMEOUT_S:g} 秒，候选端点 ≤{MAX_CANDIDATES} 个，"
        f"额外端口/用户目录各 ≤{MAX_EXTRA_PORTS}/{MAX_EXTRA_USER_DATA_DIRS} 个"
        "（超出即截断并在回执里写明，不静默少探）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "可选：直接探测的 CDP base url（如 http://127.0.0.1:9222）",
            },
            "ports": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "可选：在默认端口（"
                    + ", ".join(str(p) for p in DEFAULT_PROBE_PORTS)
                    + f"）之外额外探测的端口；与默认端口合并去重，额外至多 {MAX_EXTRA_PORTS} 个"
                ),
            },
            "user_data_dirs": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "可选：额外探测的 Chrome 用户数据目录（读取 DevToolsActivePort 落盘事实）；"
                    f"与缺省常见目录合并，额外至多 {MAX_EXTRA_USER_DATA_DIRS} 个"
                ),
            },
            "timeout_s": {
                "type": "number",
                "description": (
                    f"可选：单端点探测超时秒（默认 {DEFAULT_TIMEOUT_S}，上限 {MAX_TIMEOUT_S:g}）；"
                    f"整体探测另有 {TOTAL_TIMEOUT_S:g} 秒总时限"
                ),
            },
        },
    }

    def execute(self, **kwargs) -> ToolResult:
        url = str(kwargs.get("url", "") or "").strip()
        timeout_s = kwargs.get("timeout_s", DEFAULT_TIMEOUT_S)
        try:
            timeout = float(timeout_s)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_S
        timeout = min(max(timeout, 0.2), MAX_TIMEOUT_S)
        ports = kwargs.get("ports") or None
        if isinstance(ports, list):
            ports = [p for p in ports if isinstance(p, int) and not isinstance(p, bool)]
        else:
            ports = None
        raw_dirs = kwargs.get("user_data_dirs") or None
        dirs = [str(d) for d in raw_dirs] if isinstance(raw_dirs, list) else None
        candidates = [url] if url else discover_cdp_candidates(ports=ports, user_data_dirs=dirs)
        truncated = len(candidates) > MAX_CANDIDATES
        if truncated:
            candidates = candidates[:MAX_CANDIDATES]
        lines = [f"[探测] 候选端点 {len(candidates)} 个（来源：已配置值 / 常见端口 / DevToolsActivePort）"]
        if truncated:
            lines.append(
                f"[说明] 候选端点超过上限 {MAX_CANDIDATES} 个，已截断，只探测前 {MAX_CANDIDATES} 个。"
            )
        lines.append(
            f"[说明] 整体探测时限 {TOTAL_TIMEOUT_S:g} 秒；单端点超时上限 {MAX_TIMEOUT_S:g} 秒。"
        )
        deadline = time.monotonic() + TOTAL_TIMEOUT_S
        reachable: list[str] = []
        for candidate in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                lines.append("[说明] 已达整体探测时限，剩余候选端点未探测。")
                break
            report = probe_cdp_endpoint(
                candidate, timeout_s=min(timeout, remaining), deadline=deadline
            )
            if report["reachable"]:
                reachable.append(report["url"])
                lines.append(
                    f"[端点] {report['url']} → 可达 "
                    f"browser={report['browser'] or '未知'} 协议={report['protocol_version'] or '未知'} "
                    f"目标数={report['target_count'] if report['target_count'] is not None else '未知'}"
                )
                if report.get("note"):
                    lines.append(f"[说明] {report['note']}")
            else:
                lines.append(f"[端点] {report['url']} → 不可达（{report['error']}）")
        if reachable:
            lines.append(
                f"[生效指引] 将 {_ENV_HINT}={reachable[0]} 写入 LFL 服务环境并重启服务，"
                "browser_perceive 才会在下一次会话注册；本工具不改配置，也不放宽该显式 opt-in。"
            )
        else:
            lines.append(
                f"[生效指引] 未发现可达端点：确认浏览器以 --remote-debugging-port 启动"
                f"（并满足 {_CHROME_POLICY_NOTE}），再重试本工具。"
            )
        lines.append(f"[说明] {_CHROME_POLICY_NOTE}")
        lines.append("[说明] 本探针只读取端点元信息（版本/协议/目标计数），不读取页面内容。")
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(lines),
            tool_call_id="",
            tool_name=self.name,
        )
