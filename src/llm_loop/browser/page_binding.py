"""EVO-20261007-11ae668f：显式页面绑定控制器。

多标签窗口下的确定性决策通道：调用方（模型/用户）显式指定 target_id，
controller 负责把感知 host 与 mutation actuator 原子地换绑到同一页面，
并同步更新 channel binding coordinator 身份。

边界（全部保留，不放宽）：
- 不自动选择页面（无 latest/most-active 启发式）。
- 不允许跨 Chrome 实例换绑（coordinator.rebind 强制同 browser_ws_uuid）。
- 换页必须显式发起；target_id 不在当前清单 ⇒ 确定性失败并返回清单。
- 换页后两 host 的既有会话/绑定全部丢弃，后续 capture/actuation 重新建绑
  并重新走 attestation 冻结。
"""

from __future__ import annotations

import threading
from typing import Protocol

from llm_loop.browser.channel_binding import BrowserChannelBindingCoordinator
from llm_loop.browser.errors import PageRecord, PageTargetNotFoundError

__all__ = ["BrowserPageBindingController"]


class _RebindableHost(Protocol):
    """感知 host 与 mutation actuator 都满足的最小 rebind 协议。"""

    def list_pages(self) -> list[PageRecord]: ...

    def rebind_target(self, target_id: str) -> PageRecord: ...


class BrowserPageBindingController:
    """单点协调：list_pages 只读清单 + rebind 两 host 原子换页。"""

    def __init__(
        self,
        perception_host: _RebindableHost,
        mutation_host: _RebindableHost | None = None,
        coordinator: BrowserChannelBindingCoordinator | None = None,
    ) -> None:
        self._perception_host = perception_host
        self._mutation_host = mutation_host
        self._coordinator = coordinator
        self._rebind_lock = threading.Lock()

    def attach_mutation_host(self, mutation_host: _RebindableHost) -> None:
        """factory 装配序补偿：mutation actuator 常在感知 host 之后构造。

        仅允许从 None 挂载一次；重复挂载/替换 ⇒ RuntimeError（防静默换芯）。
        """

        with self._rebind_lock:
            if self._mutation_host is not None:
                raise RuntimeError(
                    "BrowserPageBindingController.attach_mutation_host: already attached"
                )
            self._mutation_host = mutation_host

    def list_pages(self) -> list[PageRecord]:
        """只读页面清单（以感知 host 的 /json/list 为准）。"""

        return self._perception_host.list_pages()

    def current_binding(self) -> dict[str, str] | None:
        """当前 coordinator 绑定身份（未建绑 ⇒ None）。"""

        if self._coordinator is None:
            return None
        binding = self._coordinator.binding
        if binding is None:
            return None
        return {
            "browser_ws_uuid": binding.browser_ws_uuid,
            "target_id": binding.target_id,
            "target_ws_url": binding.target_ws_url,
        }

    def rebind(self, target_id: str) -> dict[str, str]:
        """显式换页：清单校验 → coordinator 重绑 → 两 host 重绑。

        返回 {"page_id","url","title","websocket_url"}。任一步确定性失败即抛
        PageTargetNotFoundError（带当前清单）/ RuntimeError（跨实例等），
        失败时两个 host 保持原绑定不变（host 重绑在 coordinator 之后，
        coordinator 失败则两 host 均未动；host 间顺序失败属部分失败，
        由下次建绑的三字段一致性检查兜底暴露，不会静默漂移）。
        """

        raw = str(target_id or "").strip()
        if not raw:
            raise ValueError("rebind requires a non-empty explicit target_id")
        with self._rebind_lock:
            records = self.list_pages()
            record = None
            for candidate in records:
                if candidate.page_id == raw:
                    record = candidate
                    break
            if record is None:
                raise PageTargetNotFoundError(raw, records)
            if self._coordinator is not None:
                binding = self._coordinator.binding
                if binding is not None:
                    self._coordinator.rebind(
                        binding.browser_ws_uuid, record.page_id, record.websocket_url
                    )
            self._perception_host.rebind_target(record.page_id)
            if self._mutation_host is not None:
                self._mutation_host.rebind_target(record.page_id)
            return record.to_dict()
