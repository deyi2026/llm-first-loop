"""分层前缀 PoC（GOAL-20260829-7483e375 T2）.

设计: docs/local/DESIGN-PREFIX-LAYERED-20260829.md
- 锚层 = Top8 高频工具全量 schema + 全工具 80 字符索引（字节跨轮冻结）
- 动态层 = 任务首消息关键词检索相关工具，全量 schema 尾部追加（只增不减，
  保前缀缓存稳定）
- 逃生门 = get_tool_schema（锚层内全量注入，模型始终可取任意工具详情）

频率依据（镜像 data/audit/action_trace.jsonl 30,584 行 / 6,521 次调用）:
Top3 = 82.1%，Top8 = 92.0%，Top10 = 94.9%。
"""

from __future__ import annotations

from typing import Any

# 锚层全量工具（频率 Top7 + 逃生门自身，实测覆盖 92.0% 调用）
ANCHOR_TOOLS: tuple[str, ...] = (
    "execute_command",
    "read_file",
    "edit_file",
    "job_output",
    "architecture_status",
    "search_records",
    "search_files",
    "get_tool_schema",  # 逃生门配套（机制必需）
)

INDEX_DESC_CHARS = 80
DYNAMIC_MAX_TOOLS = 5

# 动态层关键词表（初版词法匹配；M4.3 bge-small-zh 就绪后升级语义检索）
_TOOL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "web_fetch": ("网页", "链接", "http", "url", "抓取", "打开这个", "在线文档"),
    "web_search": ("搜索", "查一下", "查资料", "最新", "论文", "scholar", "搜索结果", "网上"),
    "read_image": ("图片", "截图", "图像", "img", "png", "jpg", "流程图", "界面图"),
    "schedule": ("定时", "提醒", "分钟后", "每小时", "每天", "周期性", "到点"),
    "schedule_cancel": ("取消提醒", "取消定时"),
    "inspect_code": ("代码结构", "有哪些类", "有哪些函数", "import 索引", "模块结构", "ast"),
    "search_docs": ("规则", "设计稿", "反思", "评估报告", "spec", "docs/"),
    "search_archive": ("压缩", "找回", "原文", "早期消息", "被压缩的"),
    "retry_tool": ("重试", "重新执行", "retry"),
    "adjust_strategy": ("调参数", "max_iterations", "timeout"),
    "save_experience": ("沉淀经验", "经验库", "save_experience"),
    "submit_evolution": ("演进建议", "架构改进", "submit_evolution"),
    "model_catalog": ("模型目录", "可用模型", "换模型", "成本档"),
    "switch_model": ("切换模型", "更便宜的模型", "本地模型"),
    "send_feishu_message": ("发到飞书", "飞书消息", "通知我"),
    "create_feishu_doc": ("飞书文档", "生成文档"),
    "send_feishu_attachment": ("发文件给我", "发附件"),
    "code_review": ("代码审查", "code_review", "自查"),
    "grill_me": ("设计评审", "盘问", "grill"),
    "stop_slop": ("去 ai 味", "清洗文本", "slop"),
    "handoff_now": ("交接", "handoff", "存档进度"),
    "playwright_test": ("端到端", "e2e", "浏览器测试"),
    "playwright_exec": ("浏览器脚本", "登录态", "渲染页面"),
    "spawn_subagent": ("子代理", "拆解成子任务", "并行调研"),
    "workflow_run": ("工作流", "编排", "并行派发"),
    "dsh_task": ("dsh", "headless", "大上下文长任务"),
    "fix_loop": ("修复循环", "自动迭代修复"),
    "task_create": ("建任务", "拆解子任务", "task_create"),
    "task_update": ("更新任务状态", "task_update"),
    "task_frontier": ("任务图", "frontier", "当前可执行集"),
    "checkpoint_goal": ("里程碑", "checkpoint"),
    "create_goal": ("建目标", "create_goal"),
}


class LayeredPrefixState:
    """动态层追加式状态（run 级）: 只增不减，保证已注入前缀字节稳定."""

    def __init__(self) -> None:
        self._injected: list[str] = []  # 已注入动态层工具名（注入序）
        self._first_select_done: bool = False

    @property
    def injected(self) -> tuple[str, ...]:
        return tuple(self._injected)

    def select_dynamic(
        self, task_text: str, all_names: set[str], *, anchor: tuple[str, ...] = ANCHOR_TOOLS
    ) -> list[str]:
        """任务首消息检索: 关键词命中 → 排除锚层/已注入 → 按 hit 顺序取前 N.

        首次调用后 _first_select_done 置位；后续调用仅在响应文本命中
        新关键词时返回新工具名（增量），调用方追加注入。
        """
        text = (task_text or "").lower()
        picked: list[str] = []
        for tool_name, keywords in _TOOL_KEYWORDS.items():
            if tool_name in anchor or tool_name in self._injected:
                continue
            if tool_name not in all_names:
                continue  # 注册表无此工具（配置差异），跳过
            if any(kw in text for kw in keywords):
                picked.append(tool_name)
        new = picked[:DYNAMIC_MAX_TOOLS]
        self._first_select_done = True
        return new

    def mark_injected(self, names: list[str]) -> None:
        """登记已注入动态层（追加式，不重复）."""
        for n in names:
            if n not in self._injected:
                self._injected.append(n)


def build_layered_schemas(
    registry: Any,
    task_text: str,
    state: LayeredPrefixState,
    *,
    full_schemas_fn=None,
    index_schemas_fn=None,
) -> list[dict]:
    """装配分层 schema 列表: 锚层（Top8 全量 + 其余 index）+ 动态层全量（尾部）.

    字节稳定性契约:
    - 锚层部分每轮重建但字节恒定（registry 装配序稳定 + index 确定性渲染）
    - 动态层只增不减，新工具仅在列表尾部追加
    依赖注入参数（*_fn）仅供单测替换；生产路径直接用 registry 方法。
    """
    full_fn = full_schemas_fn or registry.schemas
    index_fn = index_schemas_fn or registry.index_schemas

    full_list = full_fn(lazy=False)
    index_list = index_fn()
    full_map = {t["name"]: t for t in full_list}

    # 锚层: Top8 全量（存在才收，防配置差异）→ 其余工具 index 条目
    anchor_full = [full_map[n] for n in ANCHOR_TOOLS if n in full_map]
    anchor_names = {t["name"] for t in anchor_full}
    anchor_index = [t for t in index_list if t["name"] not in anchor_names]

    # 动态层: 首选任务文本检索；已注入集合延续（只增）
    all_names = {t["name"] for t in full_list}
    new_tools = state.select_dynamic(task_text, all_names)
    state.mark_injected(new_tools)
    dynamic_full = [full_map[n] for n in state.injected if n in full_map]

    return anchor_full + anchor_index + dynamic_full
