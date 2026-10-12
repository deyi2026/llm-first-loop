"""EVO-20261007-11ae668f：多标签显式换绑（page list + target_id rebind）单测。

覆盖：
1. 多页无显式 target ⇒ MultiPageAmbiguityError（含页面清单），不做自动选择。
2. host list_pages 只读清单。
3. host rebind_target：命中清单 ⇒ 换绑+丢弃旧会话；未命中 ⇒ PageTargetNotFoundError。
4. coordinator.rebind：同 uuid 允许、跨 uuid 拒绝、无绑定时等价建绑。
5. controller：两 host 原子换绑 + target 不存在时确定性失败。
6. coordinator 换绑后 target 身份已更新且无 established 回调（首记录语义保留）。
"""

from __future__ import annotations

import json

import pytest

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.channel_binding import BrowserChannelBindingCoordinator
from llm_loop.browser.errors import (
    MultiPageAmbiguityError,
    PageTargetNotFoundError,
    page_records_from_targets,
)
from llm_loop.browser.page_binding import BrowserPageBindingController


TWO_PAGES = [
    {
        "id": "page-A",
        "type": "page",
        "title": "登录页",
        "url": "https://passport.example.com/login",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/page-A",
    },
    {
        "id": "page-B",
        "type": "page",
        "title": "主站",
        "url": "https://www.example.com/",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/page-B",
    },
    {
        "id": "not-a-page",
        "type": "iframe",
        "url": "about:blank",
    },
]


def _perception_host(pages: list[dict], **kwargs) -> CdpReadOnlyBrowserHost:
    return CdpReadOnlyBrowserHost(
        "http://127.0.0.1:9222",
        http_get_json=lambda url: json.loads(json.dumps(pages)),
        **kwargs,
    )


def _mutation_host(pages: list[dict], **kwargs) -> CdpBrowserMutationActuator:
    return CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        http_get_json=lambda url: json.loads(json.dumps(pages)),
        **kwargs,
    )


def test_multi_page_without_target_raises_structured_ambiguity() -> None:
    host = _perception_host(TWO_PAGES)
    with pytest.raises(MultiPageAmbiguityError) as excinfo:
        host._resolve_target()
    pages = excinfo.value.pages
    assert [page.page_id for page in pages] == ["page-A", "page-B"]
    assert "no fuzzy binding / no auto selection" in str(excinfo.value)


def test_list_pages_is_readonly_normalized_inventory() -> None:
    host = _perception_host(TWO_PAGES)
    records = host.list_pages()
    assert [record.page_id for record in records] == ["page-A", "page-B"]
    assert records[0].url == "https://passport.example.com/login"
    assert records[1].websocket_url.endswith("page-B")


def test_page_records_from_targets_filters_non_page_types() -> None:
    records = page_records_from_targets(TWO_PAGES)
    assert [record.page_id for record in records] == ["page-A", "page-B"]


def test_rebind_target_hits_and_updates_configured() -> None:
    host = _perception_host(TWO_PAGES)
    record = host.rebind_target("page-B")
    assert record.page_id == "page-B"
    # 下一次 resolve 直接确定性命中新页（不依赖单页假设）
    assert host._resolve_target()["id"] == "page-B"


def test_rebind_target_unknown_id_fails_deterministically() -> None:
    host = _perception_host(TWO_PAGES)
    with pytest.raises(PageTargetNotFoundError) as excinfo:
        host.rebind_target("page-C")
    assert [page.page_id for page in excinfo.value.pages] == ["page-A", "page-B"]


def test_mutation_host_multi_page_ambiguity_same_contract() -> None:
    host = _mutation_host(TWO_PAGES)
    with pytest.raises(MultiPageAmbiguityError):
        host._resolve_target()
    records = host.list_pages()
    assert [record.page_id for record in records] == ["page-A", "page-B"]


def test_mutation_host_rebind_target_switches_page() -> None:
    host = _mutation_host(TWO_PAGES)
    record = host.rebind_target("page-A")
    assert record.page_id == "page-A"
    assert host._resolve_target()["id"] == "page-A"


def test_coordinator_rebind_same_instance_updates_target_identity() -> None:
    coordinator = BrowserChannelBindingCoordinator()
    established = []
    coordinator.on_established(lambda binding: established.append(binding))
    coordinator.require_match("browser-uuid-1", "page-A", "ws://x/page-A")
    rebound = coordinator.rebind(
        "browser-uuid-1", "page-B", "ws://x/page-B"
    )
    assert rebound.target_id == "page-B"
    assert rebound.browser_ws_uuid == "browser-uuid-1"
    assert len(established) == 1  # rebind 不触发 established 回调（首记录语义保留）
    binding = coordinator.binding
    assert binding is not None and binding.target_id == "page-B"


def test_coordinator_rebind_cross_instance_rejected() -> None:
    coordinator = BrowserChannelBindingCoordinator()
    coordinator.require_match("browser-uuid-1", "page-A", "ws://x/page-A")
    with pytest.raises(RuntimeError, match="cross-instance rebind is forbidden"):
        coordinator.rebind("browser-uuid-2", "page-B", "ws://x/page-B")


def test_coordinator_rebind_without_binding_establishes_identity() -> None:
    coordinator = BrowserChannelBindingCoordinator()
    binding = coordinator.rebind("browser-uuid-1", "page-B", "ws://x/page-B")
    assert binding.target_id == "page-B"
    assert coordinator.binding is not None


def test_controller_rebind_atomically_updates_both_hosts() -> None:
    perception = _perception_host(TWO_PAGES)
    mutation = _mutation_host(TWO_PAGES)
    coordinator = BrowserChannelBindingCoordinator()
    controller = BrowserPageBindingController(
        perception_host=perception,
        mutation_host=mutation,
        coordinator=coordinator,
    )
    receipt = controller.rebind("page-B")
    assert receipt["page_id"] == "page-B"
    assert perception._resolve_target()["id"] == "page-B"
    assert mutation._resolve_target()["id"] == "page-B"


def test_controller_rebind_unknown_target_returns_page_list() -> None:
    perception = _perception_host(TWO_PAGES)
    mutation = _mutation_host(TWO_PAGES)
    controller = BrowserPageBindingController(
        perception_host=perception,
        mutation_host=mutation,
    )
    with pytest.raises(PageTargetNotFoundError) as excinfo:
        controller.rebind("page-Z")
    assert [page.page_id for page in excinfo.value.pages] == ["page-A", "page-B"]
    # 失败后两个 host 均未换绑
    with pytest.raises(MultiPageAmbiguityError):
        perception._resolve_target()


def test_controller_attach_mutation_host_once_only() -> None:
    perception = _perception_host(TWO_PAGES)
    controller = BrowserPageBindingController(perception_host=perception)
    controller.attach_mutation_host(_mutation_host(TWO_PAGES))
    with pytest.raises(RuntimeError, match="already attached"):
        controller.attach_mutation_host(_mutation_host(TWO_PAGES))
