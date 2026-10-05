"""BrowserChannelBinding：两 host 共享的浏览器通道绑定身份（DESIGN-20261005 v4 §4.3，S3a）。

问题（v4-G3）：CdpReadOnlyBrowserHost 与 CdpBrowserMutationActuator 各自独立首绑
（各自 /json/list 选 target），没有任何机械机制证明两者在同一个浏览器进程上。
若感知与执行恰落在两个不同 Chrome（同 port 先后换主 / 多实例同暴露），模型会
"看见 A、操作 B"。

机制：factory 单点创建一个 BrowserChannelBindingCoordinator 注入两 host。
- 绑定身份 = browser ws UUID（GET /json/version 的 webSocketDebuggerUrl path 段，
  浏览器进程级、每次重启更换）+ target_id + target ws 全串。
- 首个到达绑定点 host 建立身份；后到者三字段全匹配才放行，任一不匹配 ⇒ 拒绝
  （no cross-instance drift，语义与既有 per-host no-silent-rebind 一致）。
- coordinator=None（直接构造 host 的 harness/qualification 用法）⇒ 行为与 S3a
  之前完全一致（TCP 行为不变约束）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

__all__ = [
    "BrowserChannelBinding",
    "BrowserChannelBindingCoordinator",
    "extract_browser_ws_uuid",
]


@dataclass(frozen=True)
class BrowserChannelBinding:
    browser_ws_uuid: str
    target_id: str
    target_ws_url: str
    created_at: float = field(default_factory=time.time)


def extract_browser_ws_uuid(websocket_debugger_url: str) -> str:
    """/json/version.webSocketDebuggerUrl（ws://127.0.0.1:P/devtools/browser/<uuid>）→ uuid 段。"""
    raw = str(websocket_debugger_url or "").strip()
    marker = "/devtools/browser/"
    idx = raw.rfind(marker)
    if idx < 0:
        raise RuntimeError(
            f"/json/version webSocketDebuggerUrl 缺 /devtools/browser/<uuid> 段: {raw!r}"
        )
    uuid = raw[idx + len(marker):].strip("/")
    if not uuid:
        raise RuntimeError(f"browser ws uuid 为空: {raw!r}")
    return uuid


class BrowserChannelBindingCoordinator:
    """首个绑定者建立身份；后到者必须三字段全匹配。线程安全。"""

    def __init__(self) -> None:
        self._binding: BrowserChannelBinding | None = None
        self._lock = threading.Lock()

    @property
    def binding(self) -> BrowserChannelBinding | None:
        with self._lock:
            return self._binding

    def require_match(
        self, browser_ws_uuid: str, target_id: str, target_ws_url: str
    ) -> BrowserChannelBinding:
        """无既有 binding ⇒ 建立；有 ⇒ 三字段任一不匹配即拒绝。"""
        with self._lock:
            if self._binding is None:
                self._binding = BrowserChannelBinding(
                    browser_ws_uuid=browser_ws_uuid,
                    target_id=target_id,
                    target_ws_url=target_ws_url,
                )
                return self._binding
            current = self._binding
        # 比对放锁外（只读不可变对象）
        mismatches: list[str] = []
        if browser_ws_uuid != current.browser_ws_uuid:
            mismatches.append(
                f"browser ws uuid: coordinator={current.browser_ws_uuid} vs now={browser_ws_uuid}"
                "（端口背后的 Chrome 进程已更换）"
            )
        if target_id != current.target_id:
            mismatches.append(
                f"target_id: coordinator={current.target_id} vs now={target_id}"
            )
        if target_ws_url != current.target_ws_url:
            mismatches.append(
                f"target ws url: coordinator={current.target_ws_url} vs now={target_ws_url}"
            )
        if mismatches:
            raise RuntimeError(
                "Browser channel binding mismatch — 感知/执行两 host 试图落在不同浏览器通道上; "
                "no cross-instance drift; 明确重建方式: 重启 web 重建两 host。mismatch: "
                + "; ".join(mismatches)
            )
        return current
