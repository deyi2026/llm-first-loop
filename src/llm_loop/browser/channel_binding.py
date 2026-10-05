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
from typing import Callable

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
    # S3b attestation（S0 结论 ②）：首绑 host 冻结，另一 host 必须一致，不符即拒
    argv_sha256: str = ""
    verdict: str = ""
    checked_at: float = 0.0


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
        # S3b：建绑/attestation 冻结后的落盘回调（factory 注入，写 store 首记录）
        self._listeners: list[Callable[[BrowserChannelBinding], None]] = []

    @property
    def binding(self) -> BrowserChannelBinding | None:
        with self._lock:
            return self._binding

    def on_established(self, callback: Callable[[BrowserChannelBinding], None]) -> None:
        """注册建绑回调；若绑定已存在则立即补调一次。"""
        with self._lock:
            self._listeners.append(callback)
            current = self._binding
        if current is not None:
            callback(current)

    def require_match(
        self,
        browser_ws_uuid: str,
        target_id: str,
        target_ws_url: str,
        *,
        argv_sha256: str = "",
        verdict: str = "",
        checked_at: float = 0.0,
    ) -> BrowserChannelBinding:
        """无既有 binding ⇒ 建立；有 ⇒ 身份三字段任一不匹配即拒绝。

        attestation 三字段（S3b）：既有 binding 已冻结且新值非空 ⇒ 必须一致
        （argv_sha256/verdict；checked_at 只留痕不比对）；既有未冻结 ⇒ 补冻结并回调。
        """
        with self._lock:
            if self._binding is None:
                self._binding = BrowserChannelBinding(
                    browser_ws_uuid=browser_ws_uuid,
                    target_id=target_id,
                    target_ws_url=target_ws_url,
                    argv_sha256=argv_sha256,
                    verdict=verdict,
                    checked_at=checked_at,
                )
                established = self._binding
                listeners = list(self._listeners)
            else:
                current = self._binding
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
                if (
                    argv_sha256
                    and current.argv_sha256
                    and argv_sha256 != current.argv_sha256
                ) or (verdict and current.verdict and verdict != current.verdict):
                    raise RuntimeError(
                        "Browser channel binding mismatch — 感知/执行两 host 的 attestation"
                        f" 不一致（已有 argv_sha256={current.argv_sha256[:12]}… verdict="
                        f"{current.verdict} vs 新 argv_sha256={argv_sha256[:12]}… verdict="
                        f"{verdict}）；no cross-instance drift; 重启 web 重建两 host。"
                    )
                if argv_sha256 and not current.argv_sha256:
                    self._binding = BrowserChannelBinding(
                        browser_ws_uuid=current.browser_ws_uuid,
                        target_id=current.target_id,
                        target_ws_url=current.target_ws_url,
                        created_at=current.created_at,
                        argv_sha256=argv_sha256,
                        verdict=verdict,
                        checked_at=checked_at,
                    )
                    established = self._binding
                    listeners = list(self._listeners)
                else:
                    return current
        # 回调放锁外，避免监听器重入死锁
        for listener in listeners:
            listener(established)
        return established
