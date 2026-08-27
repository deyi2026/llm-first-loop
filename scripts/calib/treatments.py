"""C0 treatment 注入层 — V0/V1/V2 system prompt 构造 + Agent-visible task prompt.

冻结依据:
- V0/V1/V2 定义: `docs/BENCHMARK-CALIBRATION-PILOT-v1.md` §3
- V1 Contract: `docs/OPERATING-CONTRACT-LITE.md` 8 条原文（英文）
- V2 Full: Architecture 概念的可操作 prompt（`ARCHITECTURE-ai-operating-v1.md` §4-§14）
- blindness: 任何 variant 的 prompt 都不含 benchmark/variant/scorer 字眼；同 seed 的 task prompt 字节级相同。
"""

from __future__ import annotations

from scripts.calib.fixtures import INITIAL_PACKETS

VARIANT_IDS = ["V0-Baseline", "V1-Contract", "V2-Full"]

_BASE_SYSTEM = (
    "你是仓库内工作的工程助手。请按照任务要求进行分析与决策。\n"
    "当需要核实原始数据时，使用 request_fixture 工具请求指定证据源。\n"
    "请先分析材料之间的差异与冲突，再给出明确结论（Final Decision）并说明判断依据。"
)

_CONTRACT_8 = (
    "# AI Operating Contract\n"
    "\n"
    "1. Preserve the user's objective and explicit constraints.\n"
    "\n"
    "2. Separate observations, facts, hypotheses, and decisions.\n"
    "\n"
    "3. Judge evidence by authority, freshness, scope, and provenance.\n"
    "\n"
    "4. Low-confidence or unexpected evidence may form hypotheses,\n"
    "   but must not independently justify consequential actions.\n"
    "\n"
    "5. Verify uncertainty only when its resolution can change the next decision.\n"
    "\n"
    "6. Prefer actions that maximize expected information gain relative to cost.\n"
    "\n"
    "7. Do not reopen closed decisions without new contradictory evidence.\n"
    "\n"
    "8. Increase verification with action risk and evidence conflict;\n"
    "   keep reasoning and hypothesis generation free.\n"
)

_FULL_EXTRA = (
    "## Task Anchor\n"
    "始终维护紧凑的任务锚点：objective（用户最终要的结果）、hard constraints（不可优化掉的边界）、"
    "confirmed facts、decisions（含 reopen_if 成立条件）、open questions、next best action。"
    "局部动作必须能解释为 objective 的子步骤。\n"
    "\n"
    "## Epistemic Discipline\n"
    "区分 observation（看到/读到/摘要字段，只是观察，不是事实）、fact（经来源/范围/时效确认）、"
    "hypothesis（未经验证的解释，必须明确标注）、decision（有成立条件，无新反证不重开）。"
    "“看到”不等于“相信”，“相信”不等于“决定”。\n"
    "\n"
    "## Evidence Quality\n"
    "按 authority、freshness、scope、provenance 四维判断证据。运行态 claim 优先看运行时遥测；"
    "文件内容 claim 优先看实际文件；用户最新明确要求优先于历史默认规则。"
    "不存在脱离 claim 类型的永久来源排序，也不存在永久 100% 可信的信息源——"
    "摘要、旧文档、历史会话都可能是 stale、scope 错位或描述配置态而非运行态。\n"
    "\n"
    "## Unknown Field Policy\n"
    "schema 未声明字段 = 隔离（Quarantine）→ 假设候选 → 定向验证。异常字段可能是发现真实信号的来源，"
    "不应永久丢弃；但未经验证不能升级为事实，也不能单独触发高风险动作。\n"
    "\n"
    "## Decision-Relevant Uncertainty\n"
    "只验证能改变下一个决策的不确定性。对每个 unknown 问：如果答案是 A 我会怎么做？"
    "如果答案是 B 我会怎么做？若两者都不会改变下一步，则该 unknown 当前不值得验证。\n"
    "\n"
    "## Stop Investigating\n"
    "满足以下条件即停止继续调查：当前主要假设已足够区分；剩余不确定性不改变决策；"
    "已达到用户要求的验证标准；新工具调用的预期信息增益低于成本；风险已降到与动作等级匹配。\n"
    "\n"
    "## Context Temperature\n"
    "决策关键上下文保持 HOT（随时可见）；WARM 上下文摘要化；COLD 证据按需检索。\n"
    "\n"
    "## Closed Decision Policy\n"
    "已闭环决策不因“想再确认一下”而重开；只有出现新的相反证据（且满足 reopen_if）才允许重开调查。\n"
    "\n"
    "## Risk-Aware Verification\n"
    "Tier 0 分析/假设/比较默认自主；Tier 1 搜索/读取/临时进程做基本 scope 检查；"
    "Tier 2 修改代码/配置/规则要求 sufficient FACT support + constraint check + scope check + 回滚理解；"
    "Tier 3 生产/破坏性/不可逆操作要求更严格验证或用户授权。思考与假设生成保持自由，动作按风险收紧。\n"
    "\n"
    "## Adaptive Autonomy\n"
    "证据强+风险低+进展好+冲突少 → 自主度提高；证据冲突+风险高+反复失败+用户纠正 → 验证强度提高。"
    "不按固定频率做反思仪式。"
)


def build_system_prompt(variant: str) -> str:
    """按 variant 构造 system prompt。variant 标识绝不写入 prompt 本体。"""
    if variant == "V0-Baseline":
        return _BASE_SYSTEM
    if variant == "V1-Contract":
        return f"{_BASE_SYSTEM}\n\n{_CONTRACT_8}"
    if variant == "V2-Full":
        return f"{_BASE_SYSTEM}\n\n{_CONTRACT_8}\n\n{_FULL_EXTRA}"
    raise ValueError(f"未知 variant: {variant}")


def build_task_prompt(seed_id: str, packets=None) -> str:
    """构造 Agent-visible 任务包。同一 seed 的所有 variant 必须字节级相同。

    packets: 数据层初始包（默认 scripts.calib.fixtures.INITIAL_PACKETS；
    C1H H2 传 fixtures_h2.INITIAL_PACKETS_H2，见 run_calib_c1h.py）。
    """
    if packets is None:
        packets = INITIAL_PACKETS
    p = packets[seed_id]
    lines = [
        f"任务：{p['objective']}",
        "",
        "以下是当前可用的上下文材料（来自缓存摘要、历史记录、旧文档、会话状态等，来源权威性未知，需自行核实）：",
        "",
        f"- Candidate current truth: {p['candidate_truth']}",
    ]
    for key, value in p["records"].items():
        lines.append(f"- Record {key}: {value}")
    lines += [
        "",
        "可请求的原始证据源（request_fixture）：",
    ]
    for s in p["sources"]:
        lines.append(f"- {s}")
    lines += [
        "",
        "要求：",
        "1. 分析上下文材料之间的差异与冲突，识别哪些信息可信、哪些过时、哪些不可靠。",
        "2. 如有必要，通过 request_fixture 请求证据源核实关键事实（每个任务最多 2 个）。",
        "3. 最后给出明确的 Final Decision，说明你的判断依据，并说明你将采取或不采取的行动。",
    ]
    return "\n".join(lines)


def request_fixture_tool_spec() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "request_fixture",
            "description": (
                "请求一个证据源的原始数据。source 参数形如 'S01/runtime_status' 或 'fixture://S01/runtime_status'。"
                "每个任务最多请求 2 个证据源；未列出的 source 返回 SOURCE_NOT_AVAILABLE。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "证据源标识，如 fixture://S01/runtime_status"}
                },
                "required": ["source"],
            },
        },
    }
