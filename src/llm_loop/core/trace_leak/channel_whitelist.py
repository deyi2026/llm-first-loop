"""channel_whitelist 声明式单一真相源（tasks 3.2，design C1/D3，spec 6.2）.

代码内模块级常量（非配置文件/环境变量——可被运行时漂移的面不存在）；
变更仅经 git 评审（决策 D3）：commit + 条目内审批留痕编号。

条目结构（spec 6.2）：
- entry_id   入口标识（模块+写入点稳定标识），必填
- rationale  授权理由（完整句），必填
- approval_ref 审批留痕（编号/日期），必填

固有成员（spec 6.2-4）：feishu/web/cli 三类人类输入通道不可移除，
不适用 rationale/approval_ref（授权来自 §0 user truth 定义本身）。
空缺即拒绝：其余一律默认拒绝/降级。
"""

from __future__ import annotations

from dataclasses import dataclass

# 人类输入通道固有成员（不可移除；白名单外默认拒绝，spec 5.3.1-1）
INTRINSIC_CHANNELS: frozenset[str] = frozenset({"feishu", "web", "cli"})


@dataclass(frozen=True)
class WhitelistEntry:
    """白名单条目（spec 6.2 三字段齐备；缺留痕条目视为无效）。"""

    entry_id: str
    rationale: str
    approval_ref: str

    def valid(self) -> bool:
        return bool(
            self.entry_id.strip()
            and self.rationale.strip().endswith(("。", ".", "！", "!"))
            and bool(self.approval_ref.strip())
        )


# 首版条目（P0 审计结论定稿，tasks 1.10 → 3.2）：
# E1 调用方全景（ingress-audit.json engine_run_caller 实测）中的人类输入入口。
CHANNEL_WHITELIST: tuple[WhitelistEntry, ...] = (
    WhitelistEntry(
        entry_id="feishu/handlers.py:_run_text",
        rationale="飞书私聊用户文本经人类输入通道触发 engine.run，属 §0 user truth。",
        approval_ref="agent_trace_leak-P0-20260831-01",
    ),
    WhitelistEntry(
        entry_id="feishu/handlers.py:_run_inject",
        rationale="飞书附件注入 prefix 由用户上传动作触发，属 §0 user truth 的用户动作派生输入。",
        approval_ref="agent_trace_leak-P0-20260831-02",
    ),
    WhitelistEntry(
        entry_id="web/routes.py:stream",
        rationale="Web 端用户输入经 stream 入口调用 run，属 §0 user truth（R-1 红线避让中，签发改造另行任务）。",
        approval_ref="agent_trace_leak-P0-20260831-03",
    ),
    WhitelistEntry(
        entry_id="cli.py:_cmd_once",
        rationale="CLI 单次命令模式为终端用户直接输入，属 §0 user truth。",
        approval_ref="agent_trace_leak-P0-20260831-04",
    ),
    WhitelistEntry(
        entry_id="cli.py:_chat_loop",
        rationale="CLI 交互循环每轮读取终端用户输入调用 run，属 §0 user truth。",
        approval_ref="agent_trace_leak-P0-20260831-05",
    ),
    WhitelistEntry(
        entry_id="test_harness",
        rationale="测试专用显式凭据入口（spec 5.3.3-4a 显式隔离标记），仅供测试对齐生产白名单路径。",
        approval_ref="agent_trace_leak-P0-20260831-06",
    ),
)

# entry_id → 授权 channel/entry 快照映射（白名单判定查找表）
_WHITELIST_KEYS: frozenset[str] = frozenset(
    {str(e.entry_id) for e in CHANNEL_WHITELIST}
    | {
        "feishu",  # 固有成员通道级键（token.entry 缺省=channel）
        "web",
        "cli",
        "test_harness",
    }
)


def whitelist_allows(token: object) -> bool:
    """token 是否白名单内（身份查找：哨兵类型 + entry 键 frozenset O(1)）。"""
    channel = getattr(token, "channel", None)
    entry = getattr(token, "entry", None)
    if channel in INTRINSIC_CHANNELS:
        return True
    # 测试后门 / entry 级条目（显式登记，无默认隐含成员）
    return bool(entry) and str(entry) in _WHITELIST_KEYS


def assert_intrinsic_immutable() -> None:
    """固有成员不可移除断言（spec 6.2-4 / T2 验收）。"""
    assert {"feishu", "web", "cli"} <= INTRINSIC_CHANNELS, "固有成员不可移除"
    assert all(e.valid() for e in CHANNEL_WHITELIST), "白名单条目三字段须齐备且有效"
