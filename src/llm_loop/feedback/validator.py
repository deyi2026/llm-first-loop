"""声明-回执校验 DeclarationValidator（design.md §2.1.3.4 机制三 / FR-FBK-01）.

识别 LLM 最终回答中的"完成声明"（如"已写入文件"），对照本轮真实工具回执；
不一致时如实反馈差异（声明 vs 事实），交由 LLM 更正（最多 1 次，不阻断循环）。
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from llm_loop.core.message import Message, ToolResultStatus
from llm_loop.core.run_context import current_session_id as _current_session_id
from llm_loop.timekeeping import system_local_now

# 声明动词表（写入/创建/删除/保存/修改/执行/更新/安装/下载…）
_DECLARE_VERBS = [
    "写入",
    "创建",
    "删除",
    "保存",
    "修改",
    "执行",
    "更新",
    "安装",
    "下载",
    "写到",
    "写入了",
    "已写",
    "已创建",
    "已删除",
    "已保存",
    "已修改",
    "已执行",
    "已更新",
    "已安装",
    "已下载",
    "wrote",
    "created",
    "deleted",
    "saved",
    "modified",
    "executed",
    "installed",
    "downloaded",
    "written",
]

# 每类声明对应的工具回执关键词映射（宾语匹配）
_TOOL_RECEIPT_KEYWORDS = {
    "read_file": ["读取"],
    "write_file": ["写入", "创建", "保存", "written", "created"],
    "execute_command": ["执行", "executed"],
    "web_fetch": ["抓取", "获取", "下载", "fetched"],
}

# 回执前缀标注（check() 构造回执时使用；匹配器按状态过滤时消费同一常量，
# 防两处字面量漂移）。工具名后紧跟的只有三种形态:
# `tool_name: …`（普通成功）/ `tool_name（⚠️截断…）: …`（成功但截断）/
# `tool_name（已阻断）: …`（BLOCKED，非成功证据）。
_RECEIPT_TRUNCATED_PREFIX = "（⚠️截断"
_RECEIPT_BLOCKED_PREFIX = "（已阻断）"


# EVO-20260810-50816b30: 能力陈述 vs 行为声明语义区分
# 情态/能力标志（表"能力/意愿"，非"已完成"）
_ABILITY_MARKERS = [
    "可以", "能够", "能", "可", "会", "具备", "支持",
    "can ", "could ", "may ", "might ",
]
# 完成标志（表"已完成/已发生"）
_COMPLETION_MARKERS = ["已", "了", "成功", "完成", "did", "has ", "have ", "done"]

# EVO-20260815-640fc96a: B2 计划陈述豁免标记（未来时态/规划句非完成声明）
# 仅当句子不含完成标志时豁免（"已执行计划中的迁移"仍保留校验）
_PLAN_MARKERS = ["下一步", "建议执行", "优先级", "计划", "待办", "接下来", "后续将", "即将"]

# Agency-first: negative action statements are facts about *non-execution*, not completion
# claims that require a success receipt. Keep the matcher local to the matched action verb;
# a mixed sentence containing a separate positive claim (e.g. "未修改，但已执行") must
# still be checked rather than blanket-exempted because it contains "未".
_NEGATION_PREFIXES = ("未", "并未", "没有", "从未", "未曾", "不曾", "不", "无需", "未提交")

# B3 markdown 结构行（代码 fence/表格行/引用块）为引用内容，不进入声明抽取
_MARKDOWN_STRUCT_PREFIXES = ("|", ">")

# ── EVO-20260930: cohort 分层 + 引用内容二次抽取修复 ──
# 校验器版本: 抽取/匹配语义变更时 bump。审计记录携带该字段后，历史 cohort
# （如 2026-09-03 前无 id 的 1119 行匿名段）可与当前代次切分，不再混算
# precision/误报归因（8 月旧 ±40 窗口行为 ≠ 当前整句单元行为）。
# 2026.10.07: 第三方评述句豁免（属实/见下文/见上文/详见——DC-20261007T081417368324
# 实证: 对第三方项目设计的评语被抽为完成声明）→ 抽取语义变更，bump 代次。
# 2026.10.13: 指标名词/动词名词化复合豁免前置于完成标志门（EVO-20261013-8d9410ec）
# → 抽取语义变更，bump 代次。
# 2026.10.13.2: rev2——豁免改为动词 occurrence 名词化吸收判定，修复省略主语的
# 完成声明漏检与整句豁免粒度（EVO-20261013-8d9410ec rev2）→ 抽取语义变更，bump。
# 2026.11.06.1: EVO-20261105-e2b226d6——语法级豁免三族（occurrence 级非谓语断言
# 分类）+ 35 条金标准回归集 → 抽取语义变更，bump。审计（2026-11-05 会话
# a6989bff，两轮查询去重全量 False 归因）: 误报 ~97% 稳定六族——①否定式边界
# 声明 ②疑问句/选项枚举 ③祈使建议 ④指标评述句 ⑤转述外部内容/复述检查器输出
# ⑥记录性动词文本；仅 1 条真实违规（2026-08-20 "配套更新 test_validator_semantic"
# 无对应回执）。本代次按建议落地三族句法豁免（判定而非关键词黑名单）:
#   A 否定式谓语+会话自身主语: 否定/未然/道义/惯常/受托算子直接管辖声明动词；
#   B 指标名词主语(非谓语位)吸收: occurrence 落在指标/名词化复合/枚举/标识符语境；
#   C 引号/引用块内文本: 动词全部位于引用 span，或句法归属外部文档主体（转述）。
# 防漏网约束（与既有豁免一致，宁误报不漏报）: 携带完成体（已/已经/了/完/掉/
# 过/到）且非引用、非文档归属的 occurrence 一律保留校验；金标准中真实违规样本
# 必须仍可判 False（tests/unit/test_validator_gold_standard_e2b226d6.py 强制）。
VALIDATOR_VERSION = "2026.11.06.1"

# inline code span（`...`）为引用/provenance 内容（EVO-20260930）。
# 实证 DC-20260930T080447006508: 回答引用历史审计文本（"- `✅ RULE-AI-19 已落地…`"
# 等 3 条 bullet）被重新抽为完成声明。fence/表格行/引用行已由
# _strip_markdown_structures 剥离，inline code 是同族结构性引用——声明动词全部
# 落在 span 内 → 按引用内容跳过；动词在 span 外（"已写入 `src/a.py`"）仍是自身
# 完成声明，保留（路径 token 不剥离，keyword 匹配面不变）。
_INLINE_CODE_RE = re.compile(r"`+([^`]+)`+")

# ── EVO-20260917-27cd77ed: 完整句单元 + 叙事豁免 + 匹配面扩容 + 窗口扩大 ──
# 回执双面: 匹配用长面（提案下限 ≥512，取 1024 平衡 8 轮滚动缓冲体积）；
# 人读摘要/审计落盘仍用 120 字符短面（declaration_check.jsonl 体积与消费方不变）。
_RECEIPT_DISPLAY_CHARS = 120
_RECEIPT_MATCH_CHARS = 1024

# 叙事句标记（观点/批准/征询/未来/系统自动）——统一以"无完成标志"为门槛（防漏网，
# 与能力/计划豁免同一反例约束: "已执行"类真完成声明永不因叙事词被豁免）
_NARRATIVE_MARKERS = [
    # 观点/规律（09-04 实证: "生产执行层永远是最没议价权的环节"）
    "永远", "永不", "总是", "通常", "往往", "本质上", "理论上", "原则上", "大概率", "天生",
    # 批准/决策/拒绝（实证: "批准执行"——授权或审批动作，非自身已完成动作）
    "批准", "同意", "准许", "授权", "放行", "允许", "拒绝", "决策",
    # 疑问/征询（实证: "确认是否需要我先创建…"、"要保留还是删除"、"完成了吗"）
    "是否", "需不需要", "要不要", "请确认", "请指示", "还是", "怎么办", "怎么",
    # 请求/角色（实证: "需你给出目标文件路径"、"我负责把验证和执行的脏活干到底"）
    "需你", "需要你", "请你", "负责",
    # 未来/进行中（实证: "等你确认后执行"、"正在执行的演进"）
    "再", "将要", "将会", "准备", "打算", "稍后", "随后", "正在", "待我", "等你", "待你",
    "待用户", "待动作", "待办", "待确认", "待执行", "待验证", "will ", "shall ",
    # 第三方评述/交叉引用（实证 DC-20261007T081417368324: "**执行前校验** —
    # 属实且是最讲究的部分（见下文"最值得偷的"）"是对第三方项目设计的评语，
    # 非自身动作声明，被判 false 造成假阳性）；防漏网同前: 含完成标志的真声明
    # （"已执行校验，属实"）仍保留校验
    "属实", "见下文", "见上文", "详见",
]
_NARRATIVE_ENUM_MARKERS = ("①", "②", "③", "④", "⑤", "⑥")
# 结论句（实证: "判断和方案全部成立"）
_JUDGMENT_CONCLUSION_RE = re.compile(
    r"(判断|方案|结论|假设|推理|评估|论证|决策|建议|结果)[^。！？]{0,16}?(全部|均|都)?(成立|无误|正确|属实|站得住)"
)
# 指标名词（实证: "月下载 30,031"、"23:25 更新"——数字语境的动名词，非动作声明）
_METRIC_NOUN_RE = re.compile(
    r"(下载|安装|更新|执行|写入)\s*量?\s*[:：]?\s*[\d,，]+|[\d:：]\s*(更新|下载|安装)"
)
# 动词名词化复合（实证: "execute_command 的执行环境残留"、"更新频率"——无主谓动作结构）。
# EVO-20261105-e2b226d6 扩容后缀（金标准实证）: 率/量/数（执行成功率、月下载量）、
# 失败/结果（工具执行失败、action_trace 的执行结果——均非完成断言）、包（安装包）、
# 经验（save_experience description 的"保存经验"标签语）、门槛（创建门槛）、回放
# （修改回放）。完成体邻接（已/已经/了/完/掉/过/到）仍由吸收判定阻断（见
# _all_declared_verbs_nominalized），"已保存经验"类真声明不受影响。
_VERB_NOUN_COMPOUND_RE = re.compile(
    r"(执行|写入|更新|删除|保存|安装|下载|创建|修改)"
    r"(层|器|环境|序|面|动作|日志|记录|队列|钩子|历史|状态|时间|路径|权限|顺序|策略|频率|流程|上下文"
    r"|率|量|数|失败|结果|包|经验|门槛|回放|通道|成功率)"
)
# 认知性宾语（实证: "对方案执行实质拷问"——分析/评审行为无工具回执语义）
_COGNITIVE_OBJECT_RE = re.compile(
    r"(执行|进行|开展)[^。，；]{0,8}(拷问|评审|审查|分析|评估|复盘|检查|验证|排查|调研|梳理|对比|收敛|汇报)"
)
# 第三方被动句（实证: "文章已被作者删除、下线"——外部世界状态，非自身动作）。
# 不以完成标志为门槛（"已被删除"天然含"已"），但句内出现自我主体词时保留校验。
# 注意: 台账状态引用（"EVO-…→ executed"）**不在此列**——那是早轮事实陈述，
# 应走跨轮窗口补证（C）而非静默豁免，否则真幻觉的台账声明会漏网（防漏网约束）。
_PASSIVE_VERBS_RE = re.compile(
    r"被[^。！？\n]{0,16}?(" + "|".join(_DECLARE_VERBS) + r"|下线|下架|带回|合并|标记|记录|登记|实施)"
)
_SELF_AGENTS = ("我", "我们", "子代理", "本轮", "本会话", "child", "subagent", " i ", "i'", "we ")

# ── EVO-20261105-e2b226d6: 语法级豁免三族——occurrence 级非谓语断言分类 ──
# 审计六族误报（①否定式边界 ②疑问/枚举 ③祈使建议 ④指标评述 ⑤转述外部
# ⑥记录性动词）按建议收敛为三族句法机制。判定单元是"单个声明动词 occurrence
# 是否构成会话自身的完成动作断言"，算子/结构全部为封闭语法类（否定/语气/体貌/
# 引用/名词化/枚举/归属），非内容关键词黑名单。防漏网闸门: 携带完成体
# （已/已经/了/完/掉/过/到，含动词自带的"已写/写入了"形态）且非引用、非文档
# 归属的 occurrence 一律保留校验；真实违规金标准（"配套更新
# test_validator_semantic"）必须仍可判 False（金标准回归测试强制）。

# 引用 span（族C 标记形式）: 反引号（EVO-20260930 既有）+ 引号对（直角/弯引号/
# ASCII 双引号）。实证: "声称"已执行 architecture_status 查询""（复述检查器
# 输出）、"我的规则是"…立即更新""（规则引文）。
_QUOTE_SPAN_RES = (
    re.compile(r"“[^”]{1,400}”"),
    re.compile(r'"[^"\n]{1,400}"'),
    re.compile(r"「[^」]{1,400}」"),
    re.compile(r"『[^』]{1,400}』"),
)
# 英文动词词边界: created_at/recreated 等标识符成分不构成 occurrence（实证:
# "- created_at" 字段名被抽为完成声明）。
_ASCII_VERB_RES = {
    verb: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(verb)}(?![A-Za-z0-9_])")
    for verb in _DECLARE_VERBS
    if not re.search(r"[\u4e00-\u9fff]", verb)
}
# 枚举位（族B 非谓语位）: "打开/预览/下载"、"created、dispatch"——枚举成员
# 无独立完成断言语义。完成标志紧邻（"完成删除/修复"）不吸收（防漏网）。
# 注意: 分隔符不含 "→"——台账状态行 "EVO-…→ executed" 是早轮事实陈述，
# 必须保留抽取走跨轮补证（_is_third_party_state 防漏网约束，回归测试强制）。
_ENUM_SEP_CHARS = ("/", "、")
# 英文数字-动词指标语境（族B）: "98 executed"（165 条建议 98 executed）。
_EN_METRIC_VERB_RE = re.compile(
    r"(?<![A-Za-z0-9_])\d[\d,]*\s*(?:"
    + "|".join(sorted(_ASCII_VERB_RES, key=len, reverse=True))
    + r")(?![A-Za-z0-9_])"
)
# 否定算子（族A）: 否定词（可插入轻动词/范围词）直接管辖动词。
# 金标准实证（e2b226d6）: "无 commit/task 写入"——否定词与动词间的 ASCII
# 标识符段（标识符/斜杠/空格，≤24 字且受 window 10 字上限约束）不断开管辖；
# 纯中文插入语（"由下一轮执行"的"由下一轮"）仍不匹配——真声明不误豁免。
_NEG_GOVERN_RE = re.compile(
    r"(?:并未|从未|未曾|不曾|没有|没|未|无需|暂未|不|别|无|零)"
    r"(?:做|进行|曾|再|先|进一步)?(?:任何|其他|一切)?(?:做|进行)?"
    r"[A-Za-z0-9_/.\- ]{0,24}$"
)
# 有界算子（族A）: "仅/只"完成体仅当句内另有否定式谓语才豁免——
# "仅执行了这一次命令，未做其他操作"（边界声明）vs "仅执行了这一次命令"（仍查）。
_BOUNDED_GOVERN_RE = re.compile(r"(?<!不)(?:仅|只)[^，。；！？]{0,8}$")
# 道义/情态/惯常/依循算子（族A）: 祈使/建议/能力/未然语气直接管辖动词（可隔
# ≤4 字副词）。单字情态须干净左边界（防"对应/响应/申请"内字误配）。
_MODAL_GOVERN_RE = re.compile(
    r"(?:请|务必|应该|应当|必须|需要|建议|可以|可|能够|会|将|即将|待|定期|按|按照|遵循|自行|优先|先|再)"
    r"[^，。；、！？]{0,4}$"
)
_MODAL_LEFT_OK_CHARS = set("我你您他她它咱其 ")
# 未然时间算子（族A）: "签署前删除"——"X 前 + 动词"= 事后才能发生的指示。
_PRETEMPORAL_GOVERN_RE = re.compile(r"[^，。；、！？\s]{1,6}前$")
# 受托算子（族A 边界）: "执行靠别的工具"——动词 + 靠/由/交给 + 第三方 = 非自身执行。
_DELEGATION_GOVERN_RE = re.compile(
    r"^\s*\*{0,2}\s*(?:靠|由|交给|交由)(?:别的|其他|第三方|外部|单独)?"
    r"(?:工具|系统|组件|模块|进程|人)"
)
# 条件未然（族A 句级）: "若…"条件标记 + 全部 occurrence 无完成体 + 句内无会话
# 自身主语 → 条件句/建议（"删除 4.2 自动顺延；若与股权转让配套…"）。
_CONDITIONAL_MARKERS = ("若", "如果", "一旦", "届时", "否则")
# 文档主体归属（族C 非标记形式: 转述外部内容）: 协议/条款/前置等文档名词主语 +
# 完成体动词（"协议第2.3/7.1条已写入…"、"reopen 前置已写"）。
_DOC_SUBJECT_RE = re.compile(
    r"(?:协议|条款|合同|附件|说明书|报告|文章|文档|前置)"
    r"[^，。；]{0,14}已(?:写入|写|删除|下线|登记|保存|更新|创建|安装|执行|下载)"
)
# 文档/法条锚（整句转述判定用; 裸 N.N 版本号不作锚——太泛）
_DOC_ANCHOR_RE = re.compile(r"协议|条款|合同|§|第[\d.．/]+条|附件|说明书")
# 分句切分（意念被动的分句级主语检查）
_CLAUSE_SPLIT_RE = re.compile(r"[，；、：:——]")


def _declare_verb_occurrences(text: str) -> list[tuple[str, int, int]]:
    """边界感知的声明动词 occurrence 枚举（EVO-20261105-e2b226d6）.

    中文动词维持子串匹配（既有口径）；英文动词要求词边界——
    "created_at"/"recreated" 等标识符成分不再伪报为动词 occurrence。
    """
    out: list[tuple[str, int, int]] = []
    for verb in _DECLARE_VERBS:
        ascii_re = _ASCII_VERB_RES.get(verb)
        if ascii_re is not None:
            for m in ascii_re.finditer(text):
                out.append((verb, m.start(), m.end()))
        else:
            start = 0
            while (idx := text.find(verb, start)) != -1:
                out.append((verb, idx, idx + len(verb)))
                start = idx + 1
    return sorted(out, key=lambda x: (x[1], x[2]))


def _aspect_attached(text: str, verb: str, vs: int, ve: int) -> bool:
    """完成体形态判定（防漏网闸门）: 前邻 已/已经、后邻 了/完/掉/过/到，
    或动词本身自带体标记（"已写""写入了"）。"""
    if verb.startswith("已") or verb.endswith("了"):
        return True
    if vs > 0 and text[vs - 1] == "已":
        return True
    if vs >= 2 and text[vs - 2 : vs] == "已经":
        return True
    return ve < len(text) and text[ve] in "了完掉过到"


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    """反引号 + 引号对 span（族C 标记形式）。"""
    spans = [(m.start(1), m.end(1)) for m in _INLINE_CODE_RE.finditer(text)]
    for rex in _QUOTE_SPAN_RES:
        spans.extend(m.span() for m in rex.finditer(text))
    return spans


def _nominalization_spans(text: str) -> list[tuple[int, int]]:
    """指标/名词化复合 span（族B）。"""
    return [m.span() for m in _METRIC_NOUN_RE.finditer(text)] + [
        m.span() for m in _VERB_NOUN_COMPOUND_RE.finditer(text)
    ]


def _occurrence_in_spans(vs: int, ve: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= vs and ve <= e for s, e in spans)


def _occurrence_absorbed(text: str, verb: str, vs: int, ve: int) -> bool:
    """族B: occurrence 落在指标/名词化复合、枚举位或英文数字指标语境。"""
    if _aspect_attached(text, verb, vs, ve):
        return False
    if _occurrence_in_spans(vs, ve, _nominalization_spans(text)):
        return True
    before = text[max(0, vs - 2) : vs]
    after = text[ve : ve + 2]
    if any(c in before or c in after for c in _ENUM_SEP_CHARS):
        # 完成标志紧邻不吸收（"完成删除/修复"仍是断言——防漏网）
        if not any(m in text[max(0, vs - 3) : vs] for m in ("完成", "已", "成功")):
            return True
    return _occurrence_in_spans(vs, ve, [m.span() for m in _EN_METRIC_VERB_RE.finditer(text)])


def _occurrence_governed(
    text: str, verb: str, vs: int, ve: int, *, sentence_has_negation: bool
) -> bool:
    """族A: 否定/有界/道义/未然/受托算子直接管辖动词 occurrence。"""
    window_before = text[max(0, vs - 10) : vs]
    # 否定算子用加宽窗口（30 字）: 否定词可隔 ASCII 标识符段管辖动词
    # （金标准实证 "无 commit/task 写入"——否定词距动词 14 字符）。
    # 加宽仅服务 NEG（其正则自带 ASCII 段约束与句读边界），其余算子维持紧窗。
    neg_window_before = text[max(0, vs - 30) : vs]
    aspect = _aspect_attached(text, verb, vs, ve)
    # 否定算子管辖（"未执行""未做任何修改""无执行中演进"）——完成体不因否定豁免
    if not aspect and _NEG_GOVERN_RE.search(neg_window_before):
        return True
    # 有界算子（"仅执行了这一次命令，未做其他操作"）——允许完成体，须句内另有否定
    if _BOUNDED_GOVERN_RE.search(window_before) and sentence_has_negation:
        return True
    if aspect:
        return False  # 完成体 occurrence 不因语气算子豁免（防漏网闸门）
    if m := _MODAL_GOVERN_RE.search(window_before):
        op_start = vs - len(m.group(0))
        left_ok = op_start <= 0 or (
            text[op_start - 1] in _MODAL_LEFT_OK_CHARS
            or not re.match(r"[\u4e00-\u9fff]", text[op_start - 1])
        )
        if left_ok:
            return True
    if _PRETEMPORAL_GOVERN_RE.search(window_before):
        return True
    return bool(_DELEGATION_GOVERN_RE.match(text[ve : ve + 14]))


def _clause_of(text: str, vs: int) -> tuple[int, int]:
    """包含 vs 的分句区间（按 ，；、：—— 切分）。"""
    marks = list(_CLAUSE_SPLIT_RE.finditer(text))
    bounds = [0] + [m.end() for m in marks] + [len(text)]
    starts, ends = bounds[:-1], bounds[1:]
    for s, e in zip(starts, ends):
        if s <= vs < e:
            return s, e
    return 0, len(text)


def _occurrence_attributed(text: str, verb: str, vs: int, ve: int) -> bool:
    """族C 非标记形式: 文档主体归属（转述外部内容）或意念被动（受事主语句）。

    - 文档名词主语 + 完成体（"协议第2.3/7.1条已写入"、"前置已写"）;
    - 意念被动: 分句内无会话自身主语，动词前紧邻名词主语串（"文件已删除"、
      "实质漂移已写死为必过门"）——受事主语 + 完成体 = 外部/既往状态陈述。
    自身主语（我/本轮/本会话…）在分句内出现时一律不归属（防自身声明漏网）。
    """
    if not _aspect_attached(text, verb, vs, ve):
        return False
    if _occurrence_in_spans(vs, ve, [m.span() for m in _DOC_SUBJECT_RE.finditer(text)]):
        return True
    seg_s, seg_e = _clause_of(text, vs)
    seg = text[seg_s:seg_e]
    if any(a in seg.lower() for a in _SELF_AGENTS):
        return False
    head = re.sub(r"[*#`\s]+", "", text[seg_s:vs])
    head = re.sub(r"(?:已经|已)$", "", head)
    if not head:
        return False
    return bool(re.match(r"[\u4e00-\u9fff]", head[-1]))


@dataclass
class DeclarationCheckResult:
    """一次声明-回执校验结果."""

    consistent: bool
    declarations: list[str] = field(default_factory=list)
    discrepancies: list[str] = field(default_factory=list)  # 声明了什么 vs 实际事实
    receipt_summary: list[str] = field(default_factory=list)
    cross_round_hits: list[str] = field(default_factory=list)  # EVO-20260820-409f3f60: 近 N 轮回执命中（跨轮引用）


class DeclarationValidator:
    """声明-回执校验（FR-FBK-01 / P1 OPT-01 语义匹配）."""

    def __init__(
        self,
        audit_dir: str | Path | None = None,
        *,
        semantic_matcher: Callable[[str, str], float] | None = None,
        semantic_threshold: float = 0.75,
        recent_window: int = 8,  # EVO-20260917-27cd77ed C: 3→8（早轮事实补证；VALIDATE_RECENT_WINDOW 可调）
        max_recent_sessions: int = 128,
    ) -> None:
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._semantic_matcher = semantic_matcher  # P1: 轻量语义匹配（默认 None → 纯关键词/路径）
        self._semantic_threshold = semantic_threshold
        # EVO-20260820-409f3f60: 近 N 轮回执窗口（按会话隔离）——压缩/归档移出内存的
        # 早期轮次成功回执，从历史缓存补证，区分"跨轮引用"与"真实不诚实"。
        self._recent_window = max(1, int(recent_window))
        self._max_recent_sessions = max(1, int(max_recent_sessions))
        self._recent_by_session: OrderedDict[str, deque[list[str]]] = OrderedDict()
        self._recent_guard = threading.Lock()

    def _session_buf_locked(self, sid: str) -> deque[list[str]]:
        """Return/create one session buffer while ``_recent_guard`` is held."""
        buf = self._recent_by_session.get(sid)
        if buf is None:
            buf = deque(maxlen=self._recent_window)
            self._recent_by_session[sid] = buf
        self._recent_by_session.move_to_end(sid)
        while len(self._recent_by_session) > self._max_recent_sessions:
            self._recent_by_session.popitem(last=False)
        return buf

    def reset_session(self, session_id: str) -> None:
        """Retire reconstructible cross-round receipt hints for one inactive session."""
        with self._recent_guard:
            self._recent_by_session.pop(str(session_id or ""), None)

    def check(
        self,
        final_answer: str,
        tool_messages: list[Message],
    ) -> DeclarationCheckResult:
        """比对最终回答的完成声明与本轮工具回执.

        Args:
            final_answer: LLM 最终回答文本.
            tool_messages: 本轮全部 tool 消息（含状态）.

        Returns:
            DeclarationCheckResult: consistent=True 一致；否则 discrepancies 含差异说明。
        """
        # 收集成功回执摘要（EVO-20260820-be72efb1: 截断回执标注高亮——声明匹配截断数据时
        # 提醒 LLM 该结论基于未核验摘要，抑制"截断幻觉"声明）
        # EVO-20260917-27cd77ed B: 双面回执——匹配用长面（≥512，取 1024），人读/审计仍短面。
        # 实证（DC-20260917T105728591696-f08ab5 等）: 证据出现在回执 120 字之后必然 miss。
        receipts: list[str] = []
        match_receipts: list[str] = []
        for m in tool_messages:
            content = m.content or ""
            if m.status == ToolResultStatus.SUCCESS:
                _tag = (
                    f"{_RECEIPT_TRUNCATED_PREFIX}: 部分数据未核验）"
                    if "[输出已截断]" in content
                    else ""
                )
                receipts.append(f"{m.tool_name}{_tag}: {content[:_RECEIPT_DISPLAY_CHARS]}")
                match_receipts.append(f"{m.tool_name}{_tag}: {content[:_RECEIPT_MATCH_CHARS]}")
                # 组合工具可携带真实嵌套 SUCCESS 证据；metadata 不进模型 wire，
                # 这里只扩展校验事实面，避免 subagent_result 外层摘要截断导致假阴性。
                for nested in (m.metadata or {}).get("verification_receipts", ()) or ():
                    nested_text = str(nested or "")
                    if nested_text.endswith(":success"):
                        receipts.append(f"nested:{nested_text}")
                        match_receipts.append(f"nested:{nested_text}")
            elif m.status == ToolResultStatus.BLOCKED:
                blocked = f"{m.tool_name}{_RECEIPT_BLOCKED_PREFIX}: {content[:_RECEIPT_DISPLAY_CHARS]}"
                receipts.append(blocked)
                match_receipts.append(blocked)

        # 提取完成声明
        declarations = self._extract_declarations(final_answer)

        # EVO-20260820-409f3f60: 近 N 轮历史回执（跨轮引用补证）——压缩/归档可能已把
        # 更早轮次 tool 消息移出会话消息，从本校验器维护的滚动窗口补证。
        sid = _current_session_id.get() or ""
        with self._recent_guard:
            buf = self._session_buf_locked(sid)
            history: list[str] = [r for past in buf for r in past]

        discrepancies: list[str] = []
        matched_by: list[str] = []
        cross_round_hits: list[str] = []
        cross_round_eligible = 0  # EVO-20260930 telemetry: 本轮 miss → 进入跨轮补证路径的声明数
        for decl in declarations:
            matched = self._declaration_matches_receipt(decl, match_receipts)
            if matched:
                matched_by.append(matched)
            else:
                cross_round_eligible += 1
                # 跨轮引用判定: 近 N 轮历史回执命中 → 标记跨轮引用（非真实不诚实）
                cross = self._declaration_matches_receipt(decl, history)
                if cross:
                    cross_round_hits.append(
                        f"声明: {decl}（近 {self._recent_window} 轮回执命中: {cross[:160]}）"
                    )
                else:
                    # 漂移修复（2026-08-29 会话 68fed5f5 实证）: 回执样本就近取样——
                    # 原 receipts[:3] 取最早回执（本轮首个工具），漂移轮被最早轮的
                    # model_catalog（身份话题）样本直接诱导复读"系统状态"。取最新
                    # 3 条（[-3:]）让提醒贴近当前动作，旧话题文本引用体积同步最小化。
                    # EVO-20261007-c1313de6: 判语必须停在匹配级事实——"均未见对应
                    # 成功记录"是池级断言，会被自己引用的 [退出码 0] 样本推翻
                    # （实证 DC-…b4a4fe）；真实情况是匹配未命中，不是池为空。
                    discrepancies.append(
                        f"声明: {decl} — 但本轮及近 {self._recent_window} 轮成功回执中未匹配到对应记录（回执: {receipts[-3:] or '无'}）"
                    )

        # 本轮成功回执滚入近 N 轮窗口（供下轮跨轮引用补证；EVO-20260917-27cd77ed B:
        # 滚动缓冲存匹配长面，跨轮补证同样不受 120 字截断限制）
        if match_receipts:
            with self._recent_guard:
                self._session_buf_locked(sid).append(match_receipts)

        result = DeclarationCheckResult(
            consistent=not discrepancies,
            declarations=declarations,
            discrepancies=discrepancies,
            receipt_summary=receipts,
            cross_round_hits=cross_round_hits,
        )
        self._audit(
            final_answer,
            tool_messages,
            result,
            matched_by=matched_by,
            cross_round_eligible=cross_round_eligible,
        )
        return result

    def _extract_declarations(self, answer: str) -> list[str]:
        """扫描回答文本提取完成声明（EVO-20260917-27cd77ed A: 完整句为校验单元）.

        原实现取声明动词 ±40 字符片段——跨从句劈开半句话，叙述性文字（观点/
        结论/决策/批准）被误抽为完成声明（667/2113 条 false 的主因）。现按句读符
        切完整句再匹配动词；±40 片段语义只可用于高亮，不再作为校验单元。
        """
        decls: list[str] = []
        # EVO-20260815-640fc96a B3: markdown 结构行（fence 内代码/表格行/引用块）
        # 为引用内容而非行为声明，抽取前剥离
        answer = self._strip_markdown_structures(answer)
        for sentence in self._split_sentences(answer):
            text = sentence.strip()
            if not text or text in decls:
                continue
            if not any(v in text for v in _DECLARE_VERBS):
                continue
            # EVO-20261105-e2b226d6: 词边界过滤后无有效 occurrence（如标识符
            # "created_at"）→ 非动词句，跳过
            if not _declare_verb_occurrences(text):
                continue
            # EVO-20260930: 声明动词全部位于 inline code span 内 → 引用/provenance
            # 内容（引用历史审计/证据文本），非自身完成声明，跳过。
            # 防漏网约束: 动词在 span 外（"已写入 `src/a.py`"）不豁免。
            if self._is_quoted_inline_code(text):
                continue
            # Agency-first: "未执行/没有修改/not executed" describes absence of an
            # action. It must not be turned into a fabricated completion claim that then
            # demands a success receipt. Mixed clauses with a separate positive action
            # remain checkable (see _is_negated_action_statement).
            if self._is_negated_action_statement(text):
                continue
            # EVO-20261105-e2b226d6 族A: 否定式谓语+会话自身主语 / 算子管辖未然句
            # （否定/有界/道义/惯常/未然/受托/条件——审计族①③）
            if self._is_unrealized_statement(text):
                continue
            # EVO-20260810-50816b30: 能力陈述（"可以调用工具执行命令"）非完成声明，跳过
            if self._is_ability_statement(text):
                continue
            # EVO-20260815-640fc96a B2: 计划陈述（"下一步优先级：①…②…"）未来时态
            # 本质无回执可佐证，跳过；含完成标志（"已执行计划中的命令"）不豁免
            if self._is_plan_statement(text):
                continue
            # EVO-20260917-27cd77ed A: 叙事句（观点/结论/决策/批准/征询/未来/
            # 名词化复合/认知宾语）非行为声明，跳过；含完成标志一律保留校验
            if self._is_narrative_statement(text):
                continue
            # 第三方被动/台账状态句（"文章已被作者删除"）非自身动作，跳过；
            # 句内含自我主体词（我/子代理/本轮）时不豁免（防自身声明漏网）
            if self._is_third_party_state(text):
                continue
            # EVO-20261105-e2b226d6 族C 非标记形式: 转述外部内容/文档归属
            # （"协议第2.3/7.1条已写入…""前置已写""漂移已写死为必过门"——审计族⑤）
            if self._is_restated_external(text):
                continue
            # EVO-20261105-e2b226d6: 冒号结尾标签引入行（无完成标志）——清单标题
            # 非完成断言（"一句关键不变量应直接写入设计："）
            if self._is_label_introducer(text):
                continue
            decls.append(text)
        return decls

    @staticmethod
    def _is_quoted_inline_code(text: str) -> bool:
        """声明动词是否全部位于引用 span 内（EVO-20260930 反引号 + e2b226d6 引号对）.

        豁免方向约束（与叙事/计划/能力豁免一致，宁误报不漏报）: 只要任一动词出现
        在 span 外即返回 False（视为自身声明）；仅当所有动词 occurrence 都落在
        span 内才豁免——"已写入 `src/a.py`"（动词在反引号外）永不因该规则逃脱校验，
        路径 token 也完整保留在声明文本中供 keyword 匹配。
        EVO-20261105-e2b226d6: 引用 span 从反引号扩至引号对（“”/""/「」/『』），
        实证: 复述检查器输出的 "声称"已执行 architecture_status 查询""、规则引文
        ""…有新证据立即更新"" 被误抽为完成声明。
        """
        spans = _quoted_spans(text)
        if not spans:
            return False
        for _verb, vs, ve in _declare_verb_occurrences(text):
            if not any(s <= vs and ve <= e for s, e in spans):
                return False
        return True

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """按句读符切完整句（EVO-20260917-27cd77ed A）.

        英文句点仅在真实句边界切分: 路径/版本号（src/a.py、v1.2.3）与小数中的点
        两侧均为字母数字，先行掩码保护不切句——避免把"已写入 src/a.py"劈成两截。
        """
        masked = re.sub(r"(?<=[A-Za-z0-9_])\.(?=[A-Za-z0-9_])", "\x00", text)
        parts = re.split(r"[。！？!?.\n]+", masked)
        return [p.replace("\x00", ".") for p in parts if p.strip()]

    @staticmethod
    def _is_narrative_statement(text: str) -> bool:
        """叙事句判定（EVO-20260917-27cd77ed A）: 观点/结论/决策/批准/征询/未来等句式.

        2026-09-17 实证（667 条 false 抽样全为叙述性文字）: 观点句（"生产执行层
        永远是最没议价权的环节"）、决策句（"批准执行"）、结论句（"判断和方案全部
        成立"）、指标名词（"月下载 30,031"）、名词化复合（"执行环境残留"）被误抽
        为完成声明。这些句式无回执语义也非行为声明，豁免。

        防漏网约束（与能力/计划豁免一致）: 句内出现完成标志（已/了/成功/完成）
        一律不豁免——"已写入"类真完成声明永不因叙事词逃脱校验。
        """
        lower = text.lower()
        # 疑问后缀优先于完成标志门槛（"完成了吗/执行了吗"是提问不是声明，
        # 天然含"完成/执行"但语义为征询）
        if re.search(r"(完成|执行|写入|创建|更新|保存|删除|登记)了吗", text):
            return True
        # EVO-20261013-8d9410ec rev2: 名词化吸收判定（动词 occurrence 语义分类）。
        # rev1 缺陷（外部只读审查实测复现）: 「句内无自我主体词 + 句内任意位置
        # 命中指标/复合 regex」即豁免整句。中文省略主语极常见（"已写入历史
        # 记录。"），rev1 使这类真完成声明漏检；混合句（"已保存配置，更新
        # 频率提升了"）前半真动作被后半指标词豁免。
        # rev2 豁免条件 = 句内**每个**声明动词 occurrence 都落在指标/复合
        # 匹配 span 内（名词化吸收）且无一携带完成体依附。局部命中不再
        # 豁免整句；省略主语不再导致漏检。句级自我主体词护栏保留（双保险:
        # 主体句先拦，不进入吸收判定）。
        if not any(agent in lower for agent in _SELF_AGENTS) and (
            DeclarationValidator._all_declared_verbs_nominalized(text)
        ):
            return True
        if any(m in lower for m in _COMPLETION_MARKERS):
            return False
        if any(m in lower for m in _NARRATIVE_MARKERS):
            return True
        if any(m in text for m in _NARRATIVE_ENUM_MARKERS):
            return True
        if _JUDGMENT_CONCLUSION_RE.search(text):
            return True
        return bool(_COGNITIVE_OBJECT_RE.search(text))

    @staticmethod
    def _all_declared_verbs_nominalized(text: str) -> bool:
        """EVO-20261013-8d9410ec rev2: 声明动词是否全部被名词化/指标语境吸收.

        动词 occurrence 级语义分类（根因层，非句式正则特判）:
        - absorbed: occurrence 完整落在 _METRIC_NOUN_RE / _VERB_NOUN_COMPOUND_RE
          匹配 span 内 → 该动词是名词短语成分（"更新频率"的"更新"），
          非独立谓语;
        - aspect_attached: occurrence 前邻完成体副词（已/已经）或后邻
          动态助词/结果/趋向补语（了/完/掉/过/到）→ 独立谓语且携带
          完成语义（"已写入历史"的"写入"），不可吸收。
        全部 occurrence 被吸收 → 豁免（"更新频率提升了"）；任一独立谓语
        → 不豁免，fall through 到完成标志门（"已写入历史记录"仍校验）。
        _DECLARE_VERBS 中自带体标记的组合形式（"已写""写入了"）天然
        不落在吸收 span（"写入了历史"破坏复合词边界）→ 不豁免，方向一致。
        EVO-20261105-e2b226d6: 吸收面由 _occurrence_absorbed 提供（复合后缀扩容
        + 枚举位 + 英文数字指标语境），判定口径不变（吸收 span 内且无完成体）。
        """
        occs = _declare_verb_occurrences(text)
        if not occs:
            return True  # 无有效 occurrence（如纯标识符 "created_at"）→ 无谓语可断言
        return all(_occurrence_absorbed(text, verb, vs, ve) for verb, vs, ve in occs)

    @staticmethod
    def _is_third_party_state(text: str) -> bool:
        """第三方被动句（EVO-20260917-27cd77ed A）.

        实证: "文章已被作者删除、下线"（外部世界状态，天然含"已"）被判 false。
        这类句子不以完成标志为门槛（否则全部漏掉），改用自我主体词防漏网:
        句内出现 我/我们/子代理/本轮/本会话 等主体时不豁免——
        "文件已被我删除"、"本轮实际执行…"仍需回执佐证。

        台账状态引用（"EVO-…→ executed"）刻意不豁免: 那是早轮事实陈述，
        应走跨轮窗口补证（C 项）而非静默豁免——真幻觉的台账声明必须可判 false。
        """
        lower = text.lower()
        if any(agent in lower for agent in _SELF_AGENTS):
            return False
        return bool(_PASSIVE_VERBS_RE.search(text))

    @staticmethod
    def _is_unrealized_statement(text: str) -> bool:
        """族A（EVO-20261105-e2b226d6）: 否定式谓语+会话自身主语 / 算子管辖未然句.

        全部声明动词 occurrence 均为非断言（引用 span 内 / 名词化-枚举-指标吸收 /
        否定-有界-道义-惯常-未然-受托算子管辖 / 文档归属 / 条件未然），且句级
        佐证成立之一:
        - 会话自身主语 + 否定式谓语（"本轮评估是纯指标快照，没有覆盖…""本会话
          只读，未做任何修改"——审计族①否定式边界声明）;
        - 条件未然（句内条件标记 + 无会话自身主语）;
        - 纯算子管辖（祈使/建议/能力/依循语气直接管辖每个 occurrence——审计族③）。
        防漏网: 携带完成体且未被引用/归属的 occurrence 立即返回 False
        （"本轮已执行校验""已写入 src/a.py"永不因本规则豁免）。
        """
        occs = _declare_verb_occurrences(text)
        if not occs:
            return False
        lower = text.lower()
        has_self = any(agent in lower for agent in _SELF_AGENTS)
        sentence_has_negation = any(
            p in text for p in ("未", "没有", "没", "无", "零", "不")
        )
        conditional = (not has_self) and any(m in text for m in _CONDITIONAL_MARKERS)
        for verb, vs, ve in occs:
            if _occurrence_in_spans(vs, ve, _quoted_spans(text)):
                continue
            if _occurrence_absorbed(text, verb, vs, ve):
                continue
            if _occurrence_attributed(text, verb, vs, ve):
                continue
            if _occurrence_governed(
                text, verb, vs, ve, sentence_has_negation=sentence_has_negation
            ):
                continue
            if conditional and not _aspect_attached(text, verb, vs, ve):
                continue
            return False
        if has_self and sentence_has_negation:
            return True
        if conditional:
            return True
        return all(
            _occurrence_governed(
                text, verb, vs, ve, sentence_has_negation=sentence_has_negation
            )
            or _occurrence_in_spans(vs, ve, _quoted_spans(text))
            for verb, vs, ve in occs
        )

    @staticmethod
    def _is_restated_external(text: str) -> bool:
        """族C 非标记形式（EVO-20261105-e2b226d6）: 转述外部内容/文档归属.

        - 句含文档/法条锚（协议/条款/§/第N条…）且无会话自身主语 → 整句为转述
          （审计族⑤: "**代扣代缴义务**…协议第2.3/7.1条已写入…请务必执行"）;
        - 全部 occurrence 均归属外部文档主体或意念被动（"前置已写"、
          "实质漂移已写死为必过门"）。
        自身主语在场一律不豁免（防自身声明漏网）。
        """
        lower = text.lower()
        if any(agent in lower for agent in _SELF_AGENTS):
            return False
        if _DOC_ANCHOR_RE.search(text):
            return True
        occs = _declare_verb_occurrences(text)
        if not occs:
            return False
        return all(_occurrence_attributed(text, verb, vs, ve) for verb, vs, ve in occs)

    @staticmethod
    def _is_label_introducer(text: str) -> bool:
        """标签引入行（EVO-20261105-e2b226d6）: 冒号结尾 + 无完成标志.

        "一句关键不变量应直接写入设计："（金标准实证）——冒号引入行是清单标题/
        标签行，其内容在后续行，本身不构成完成断言。防漏网: 句内出现完成标志
        （已/了/成功/完成/did/has/done）时不豁免——"我已完成以下工作："仍校验。
        """
        if not text.rstrip().endswith(("：", ":")):
            return False
        lower = text.lower()
        return not any(m in lower for m in _COMPLETION_MARKERS)

    @staticmethod
    def _strip_markdown_structures(answer: str) -> str:
        """剥离 markdown 结构行（EVO-20260815-640fc96a B3）.

        代码 fence 块整体移除；表格行（| 开头）/引用块（> 开头）按行移除——
        引用内容非行为声明（0814 误报实证：代码片段/表格行被判 False）。
        """
        text = re.sub(r"```.*?```", "", answer, flags=re.DOTALL)
        lines = [
            ln for ln in text.splitlines()
            if not ln.lstrip().startswith(_MARKDOWN_STRUCT_PREFIXES)
        ]
        return "\n".join(lines)

    @staticmethod
    def _is_negated_action_statement(text: str) -> bool:
        """Return True when the matched action is explicitly negated, with no positive action claim.

        Examples exempted: ``未执行任何修改`` / ``没有创建文件`` / ``not executed``.
        Mixed clauses such as ``未修改配置，但已执行命令`` stay eligible for checking so a
        negative clause cannot mask an independent positive completion claim.
        """
        lower = text.lower()
        action_verbs_zh = [v for v in _DECLARE_VERBS if re.search(r"[\u4e00-\u9fff]", v) and not v.startswith("已")]
        action_alt_zh = "|".join(re.escape(v) for v in action_verbs_zh)
        # The extractor's 40-char prefix is greedy, so m.group(1) can be a noun-like
        # later verb (e.g. it captures "修改" in "未执行任何修改"). Determine negation
        # from the whole extracted clause rather than trusting that one regex group.
        zh_negated = any(
            re.search(
                # e2b226d6: 允许插入轻动词（做/进行）与范围词（任何/其他）——
                # "未做任何修改"（金标准实证）此前因"做"隔断而漏豁免
                re.escape(prefix)
                + r"\s*(?:做|进行)?\s*(?:任何|其他)?\s*(?:"
                + action_alt_zh
                + r")",
                text,
            )
            for prefix in _NEGATION_PREFIXES
        )
        action_verbs_en = [
            "wrote", "created", "deleted", "saved", "modified", "executed", "installed", "downloaded", "written"
        ]
        en_alt = "|".join(re.escape(v) for v in action_verbs_en)
        en_negated = bool(
            re.search(
                r"\b(?:did\s+not|didn't|have\s+not|haven't|has\s+not|hasn't|not|never)\s+(?:" + en_alt + r")\b",
                lower,
            )
        )
        if not (zh_negated or en_negated):
            return False

        # A separate explicit positive completion in the same extracted clause wins: keep
        # the clause for verification rather than blanket-exempting it due to one negation.
        positive_zh = re.search(
            r"(?:已|已经|成功)\s*(?:" + "|".join(re.escape(v) for v in _DECLARE_VERBS if not v.startswith("已")) + r")",
            text,
        )
        positive_en = re.search(
            r"\b(?:successfully|already)\s+(?:wrote|created|deleted|saved|modified|executed|installed|downloaded)\b",
            lower,
        )
        return not bool(positive_zh or positive_en)

    @staticmethod
    def _is_plan_statement(text: str) -> bool:
        """计划陈述判定（EVO-20260815-640fc96a B2）: 含计划标记且不含完成标志.

        例: "下一步优先级：①修复 ②验证" → 计划（跳过）；
            "已执行计划中的迁移" → 完成声明（保留，有"已"标志）。
        注意: 身份声明（"我是 X"）与比较结论（"与文档一致"）不在动词表内，
        天然不进入抽取——本豁免不影响真阳性捕获。
        """
        has_plan = any(m in text for m in _PLAN_MARKERS)
        if not has_plan:
            return False
        lower = text.lower()
        has_completion = any(m in lower for m in _COMPLETION_MARKERS)
        return not has_completion

    @staticmethod
    def _is_ability_statement(text: str) -> bool:
        """能力陈述判定: 含情态动词（可以/能够/can 等）且不含完成标志（已/了/成功等）.

        例: "可以调用工具执行命令" → 能力（跳过）; "已执行命令" → 完成（保留）。
        英文情态带空格避免误伤（scan/american 等）。
        """
        lower = text.lower()
        has_ability = any(m in lower for m in _ABILITY_MARKERS)
        if not has_ability:
            return False
        has_completion = any(m in lower for m in _COMPLETION_MARKERS)
        return not has_completion

    def _declaration_matches_receipt(self, declaration: str, receipts: list[str]) -> str:
        """声明与回执匹配（返回匹配方式: keyword/semantic/""=不匹配）.

        P0: 路径/文件名包含匹配 + 动词-工具映射（保留兜底）。
        P1 OPT-01: 未命中且 semantic_matcher 可用 → 轻量语义匹配，≥ 阈值判定一致。
        匹配器异常 → 保持关键词判定结果，不伪造语义一致。
        """
        if not receipts:
            return ""
        # 关键词/路径包含匹配（P0 兜底不变）
        path_tokens = re.findall(r"[A-Za-z0-9_\-./\\]{3,}", declaration)
        for tok in path_tokens:
            if "/" in tok or "\\" in tok or "." in tok:
                for r in receipts:
                    if tok in r:
                        return "keyword"
        # 动词-回执关键词匹配（P0: 声明含动词 且 回执含该动词 → 一致）
        for verb in _DECLARE_VERBS:
            if verb in declaration and any(verb in r for r in receipts):
                return "keyword"
        # 结构化工具名匹配（EVO-20261007-c1313de6）: 声明含该工具语义动词，成功回执
        # 池中存在该工具的回执。原实现 `receipt == f"nested:{tool_name}:success"` 精确
        # 相等只覆盖组合工具嵌套证据，普通 `execute_command: [命令]… [退出码 0]` 形态
        # 结构性永不命中（跨语动词↔工具名缺口）。
        # 两重保护:
        # 1) 状态过滤: match_receipts 同时含 BLOCKED 回执（形如
        #    `execute_command（已阻断）: …`，同样以工具名开头），不能作为执行
        #    成功证据——前缀条件只接受普通/截断标注两种成功形态，显式排除
        #    已阻断标签（建议 A 审查点，回归测试强制）；
        # 2) 动词-宾语锚定: 声明含 path-like token 且未命中（能走到这里即路径匹配
        #    全部 miss）时，不得用"该类工具恰好有成功回执"泛化兜底——
        #    "已写入 output.txt" + 仅 read_file/execute_command 回执仍是 miss；
        #    无宾语锚点的泛化声明（"我已执行该校验"）才允许工具名兜底。
        lower_decl = declaration.lower()
        has_unmatched_object = any(
            "/" in tok or "\\" in tok or "." in tok for tok in path_tokens
        )
        if not has_unmatched_object:
            for tool_name, keywords in _TOOL_RECEIPT_KEYWORDS.items():
                if not any(str(k).lower() in lower_decl for k in keywords):
                    continue
                if any(
                    (
                        r.startswith(
                            (f"{tool_name}:", f"{tool_name}{_RECEIPT_TRUNCATED_PREFIX}")
                        )
                        and not r.startswith(f"{tool_name}{_RECEIPT_BLOCKED_PREFIX}")
                    )
                    or r == f"nested:{tool_name}:success"
                    for r in receipts
                ):
                    return "keyword"
        # P1 语义匹配（可选，默认关闭）
        if self._semantic_matcher is not None:
            try:
                for r in receipts:
                    score = self._semantic_matcher(declaration, r)
                    if score >= self._semantic_threshold:
                        return "semantic"
            except Exception:
                return ""  # 匹配器异常 → 保持关键词判定（不伪造）
        return ""

    def _audit(
        self,
        answer: str,
        tool_msgs: list[Message],
        result: DeclarationCheckResult,
        matched_by: list[str] | None = None,
        cross_round_eligible: int = 0,
    ) -> None:
        """审计落盘（DFX-MNT-02 / P1 matched_by 可审计）."""
        if self._audit_dir is None:
            return
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        now = system_local_now()
        sid = _current_session_id.get() or ""
        record = {
            "id": f"DC-{now.strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:6]}",
            "ts": now.isoformat(),
            "session_id": sid,
            "validator_version": VALIDATOR_VERSION,  # EVO-20260930: cohort 分层（抽取/匹配语义代次）
            "consistent": result.consistent,
            "declarations": result.declarations,
            "discrepancies": result.discrepancies,
            "cross_round_hits": result.cross_round_hits,  # EVO-20260820-409f3f60: 跨轮引用命中可审计
            "cross_round_eligible": cross_round_eligible,  # EVO-20260930: 本轮 miss 进入跨轮补证的声明数（telemetry，持续 eligible>0 且 hit=0 → 退役讨论依据）
            "session_untracked": not sid,  # sid 缺失（contextvar 未设）→ "" 共享缓冲有跨会话串扰风险，审计可见
            "tool_call_ids": list(
                dict.fromkeys(
                    str(m.tool_call_id)
                    for m in tool_msgs
                    if getattr(m, "tool_call_id", None)
                )
            ),
            "receipts": result.receipt_summary,
            "matched_by": matched_by or [],  # P1: keyword/semantic（匹配方式可审计）
            "answer_preview": answer[:200],
        }
        with (self._audit_dir / "declaration_check.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_discrepancy_feedback(result: DeclarationCheckResult) -> str:
    """构造不一致时的如实反馈消息（声明 vs 事实 + 建议，AI-first 三件套）."""
    lines = ["[声明-回执校验] 事实: 你的最终回答中存在与工具执行回执不符的完成声明："]
    for d in result.discrepancies:
        lines.append(f"  - {d}")
    lines.append("原因: 以下声明未能在本轮工具成功回执中匹配到对应记录（匹配未命中，非回执池为空）。")
    lines.append("建议: 请如实更正声明（说明实际完成情况），或重新执行相应工具后再回答。")
    return "\n".join(lines)
