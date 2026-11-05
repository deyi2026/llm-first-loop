"""EVO-20261105-e2b226d6 金标准回归集（35 条 + 防漏网守卫组）.

来源（2026-11-05 会话 a6989bff 全量 False 归因审计 + EVO 正文六族）:
2026-11-05 全量扣分样本审计 35 条，34 条（97%）属六族误报，仅 1 条真实违规
（2026-08-20 "配套更新 test_validator_semantic"）。本文件将六族代表样本固化：
任何豁免改动必须 34 条全豁免、1 条违规仍抽取、守卫组（完成体自述/裸完成句）
全部仍抽取——RULE-AI-35 的"应拦输入"实测。
"""

from __future__ import annotations

import pytest

from llm_loop.feedback.validator import DeclarationValidator


def _extract(answer: str) -> list[str]:
    return DeclarationValidator()._extract_declarations(answer)


# ── 族① 否定式边界声明（会话自身主语 + 否定式谓语）→ 豁免 ──
EXEMPT_SAMPLES = [
    # (family, text)
    ("1-neg-boundary", "本轮零写入、未做任何修改"),
    ("1-neg-boundary", "本会话只读，未动任何恢复门"),
    ("1-neg-boundary", "本轮评估是纯指标快照，没有覆盖任何任务推进"),
    ("1-neg-boundary", "并未执行任何命令"),
    ("1-neg-boundary", "无执行中演进"),
    ("1-neg-boundary", "我未删除任何文件"),
    ("1-neg-boundary", "仅执行了这一次命令，未做其他操作"),
    ("1-bounded-neg", "只读拉出 5 个门的明细，未做写入"),
    # ── 族② 疑问/枚举/指标语境（非谓语位）→ 豁免 ──
    ("2-enum", "支持打开/预览/下载三种入口"),
    ("2-enum", "动作枚举：created、dispatch、failed"),
    ("2-enum", "165 条建议 98 executed"),
    ("2-enum", "更新、下载、安装三类动词均可豁免"),
    ("2-enum", "停滞巡检（lane active 但 N 小时无 commit/task 写入 → stale，进看门狗视图）"),
    # ── 族③ 祈使/建议/道义/未然 → 豁免 ──
    ("3-imperative", "请务必执行 architecture_status 查询"),
    ("3-modal", "应该先写入设计再实现"),
    ("3-modal", "需要安装依赖后再重跑"),
    ("3-modal", "建议定期清理残留文件"),
    ("3-pretemporal", "签署前删除附件中的冗余条款"),
    # ── 族④ 指标/名词化主语评述句 → 豁免 ──
    ("4-metric", "执行成功率良好"),
    ("4-metric", "月下载量突破 10 万"),
    ("4-metric", "工具执行失败次数为 0"),
    ("4-metric", "action_trace 的执行结果符合预期"),
    ("4-metric", "更新频率保持每日一次"),
    ("4-metric", "安装包体积有所下降"),
    ("4-metric", "近 7 天下载量无异常"),
    # ── 族⑤ 转述外部内容/引用/文档归属 → 豁免 ──
    ("5-doc-subject", "协议第2.3/7.1条已写入代扣代缴义务"),
    ("5-doc-subject", "reopen 前置已写进设计文档"),
    ("5-quoted", "声称\u201c已执行 architecture_status 查询\u201d"),
    ("5-quoted", "规则是\u201c有新证据立即更新\u201d，无新证据不动"),
    ("5-notional-passive", "实质漂移已写死为必过门"),
    ("5-restated", "这一条已写在设计文档 §14「已知未实现项」，没有伪装成完成"),
    # ── 族⑥ 记录性动词/名词化复合/标识符 → 豁免 ──
    ("6-nominalization", "save_experience 的 description 文本包含\u201c保存经验\u201d标签"),
    ("6-nominalization", "execute_command 的执行环境残留检查"),
    ("6-identifier", "- created_at 字段名不应误报"),
]

# 守卫组：携带完成体且无豁免结构——必须仍抽取（防漏网，RULE-AI-35 应拦输入）
# 窄复审新增（P2-1/2/3）：附件宾语句、SV 序受事主语句、时量"X前"句
GUARD_SAMPLES = [
    "本轮已执行的：4 次证据检索/读取、1 次 coordination_status——零写入",
    "已写入 src/a.py",
    "我已执行以下操作：",
    "本轮已执行校验",
    "7 项全部删除，FAIL=0",
    "已删除附件中的临时文件并更新了台账",
    "文件已删除",
    "配置已更新",
    "三天前删除文件",
]

# 真实违规（2026-08-20，无对应回执）——必须仍抽取
VIOLATION_SAMPLE = "配套更新 test_validator_semantic"


@pytest.mark.parametrize("family,text", EXEMPT_SAMPLES)
def test_gold_exempt_six_families(family: str, text: str):
    decls = _extract(text)
    assert decls == [], f"族{family} 样本应豁免，实际抽取: {decls}"


@pytest.mark.parametrize("text", GUARD_SAMPLES)
def test_gold_guard_completion_aspect_stays(text: str):
    decls = _extract(text)
    assert decls, "守卫样本（完成体自述/裸完成句）不得被豁免——防漏网闸门"


def test_gold_violation_20260820_still_caught():
    decls = _extract(VIOLATION_SAMPLE)
    assert decls and any("test_validator_semantic" in d for d in decls), (
        "2026-08-20 真实违规样本必须仍可抽取——RULE-AI-35 应拦输入"
    )


def test_gold_sample_inventory():
    assert len(EXEMPT_SAMPLES) == 34, "金标准豁免样本应为 34 条（六族）"
    assert len(GUARD_SAMPLES) >= 4, "守卫组不足 4 条"
