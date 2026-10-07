from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageRecord:
    """一个 CDP page target 的只读身份（EVO-20261007-11ae668f）。

    只取确定性身份字段：page_id/url/title/websocket_url。不携带任何
    fuzzy 权重、活跃度、lastActive 等可用于自动选择的字段。
    """

    page_id: str
    url: str
    title: str
    websocket_url: str

    def to_dict(self) -> dict[str, str]:
        return {
            "page_id": self.page_id,
            "url": self.url,
            "title": self.title,
            "websocket_url": self.websocket_url,
        }


class MultiPageAmbiguityError(RuntimeError):
    """CDP 端点暴露多个 page 且调用方未显式指定 target_id。

    语义：不是模糊选择请求，而是"需要调用方决策"的确定性失败。
    携带只读页面清单供工具层原样返回（不绑定、不建会话）。
    """

    def __init__(self, pages: list[PageRecord]) -> None:
        self.pages = list(pages)
        ids = ", ".join(page.page_id for page in self.pages)
        super().__init__(
            "Browser CDP endpoint must expose exactly one page when target_id is omitted; "
            f"observed={len(self.pages)}; pages=[{ids}]; "
            "no fuzzy binding / no auto selection — explicit target_id required"
        )


class PageTargetNotFoundError(RuntimeError):
    """显式指定的 target_id 不在当前 CDP page 清单中（确定性失败，非模糊）。"""

    def __init__(self, target_id: str, pages: list[PageRecord]) -> None:
        self.target_id = str(target_id)
        self.pages = list(pages)
        ids = ", ".join(page.page_id for page in self.pages)
        super().__init__(
            f"explicit Browser target_id not found: {self.target_id}; "
            f"current pages=[{ids}]"
        )


def page_records_from_targets(targets: list[dict]) -> list[PageRecord]:
    """把 /json/list 原始 dict 列表规整为 PageRecord（过滤 type==page）。"""

    records: list[PageRecord] = []
    for item in targets:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "page":
            continue
        page_id = str(item.get("id") or "").strip()
        if not page_id:
            continue
        records.append(
            PageRecord(
                page_id=page_id,
                url=str(item.get("url") or ""),
                title=str(item.get("title") or ""),
                websocket_url=str(item.get("webSocketDebuggerUrl") or ""),
            )
        )
    return records
