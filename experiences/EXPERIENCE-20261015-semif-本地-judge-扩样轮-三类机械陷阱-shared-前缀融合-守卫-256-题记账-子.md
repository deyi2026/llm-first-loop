---
title: SemIf 本地 judge 扩样轮：三类机械陷阱（shared 前缀融合/守卫 256/题记账/子代理 tools 未强制）与判否能力负结果
scenario: 本地开源 judge（SemIf+Qwen3.5-4B）premise_check 扩样：预注册多轮执行，出现 shared 模式整批抛错、守卫预算中途拒批、子代理零工具要求未强制三类机械故障，以及最终判决负结果
root_cause: ""
solution: "①shared 前缀失配→改 direct 模式（每行独立全前向、同 prompt 同数学）并重预注册；②守卫按 256/题累计记账→冻结前离线算 全量 est（题数×256 与 input 合计）对齐上限；③子代理 tools=[] 不受强制→如实披露+事后审计追问（agent_followup 核查询内容）；④已见题一律转 seen_bucket 剔除主指标；⑤负结果照实入档：no 召回 2/12 与 push-yes 注入捕获是不继续推进该 judge 的充分依据"
evidence: "outputs/jev-p1l-expand-20261015/p1l_expand_report_r3.json；jev_shadow_events_v2.jsonl（§11.3 中止）；p1l_expand_report_direct.json（§11.4 中止）；v2_labels_merged.json（dual 97.7%）；tests/fixtures/jev/blind_eval_v2/manifest.json（60a17edf…）；DESIGN §11.3-§11.5 与附录 C v0.8.5→v0.8.6（artifact://v1/68376672fa5b424697f65e5e2249259f）"
tags: [semif, jev, local-judge, pre-registration, blind-eval, negative-result]
source:
  run_ref: p1l2-20261015-expand03-r3
  design: "docs/DESIGN-20261014-jev-experience-method-loop-governance.md#11.5"
  workspace: outputs/jev-p1l-expand-20261015/
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T11:33:53.840840+08:00"
updated_at: "2026-10-15T11:33:53.840840+08:00"
---

场景：对开源复现 judge（SemIf，接口模式复现 Jev：state+结构化选项→概率）做预注册扩样实验（premise_check 44 题）。三类已验证机械陷阱与最终判决负结果。

机械陷阱（均已复现+根因核源码）：
1. SemIf shared 模式前缀失配：state 前缀由"占位题"探针编码去尾 token；state JSON 与题目后缀的分词边界融合随题目文本变化，批内不一致即整批抛 ValueError（"The fixed state prefix does not match every full prompt"）。通过≠协议保证，是边界兼容的偶然。规避：--mode direct（每行独立全前向，同 prompt 同数学，无前缀校验）。
2. 守卫预算是累计记账且按固定 est_output=256/题 估算：任务集规模变化必须先离线算 全量 est（题数×256、est input 合计）再冻结上限；沿用小规模轮的上限会中途 BudgetRefused。§11.5 追加规则"预算/记账类中止必须停轮离线核算，不逐轮补丁"。
3. spawn_subagent 的 requires.tools=[] 不会被运行时强制（子代理仍可调 search_records）：预注册"零工具"标签源要么换验证手段（比对输出与给定信息封闭性），要么接受"tools=0 未强制"如实披露+事后审计追问。

判决负结果（SemIf+Qwen3.5-4B@851bf6e，direct，本 prompt）：37 题主指标 21/37（56.8%）；yes 召回 81.3% 但 no 召回 2/12（16.7%）——快照含明确反证仍高确定答 unknown（0.9+）；push-yes 注入指令成功捕获 1 例（p=0.845），push-no 被抵抗（不对称）；p_selected 高确定错判使其不可用作闸。小样本易题（uname/sw_vers 直证）会给出虚高的 5/6~全对印象，必须按失败形态分桶扩样。

方法论沉淀：预注册-冻结-执行-中止-重预注册循环在本地零成本实验里完全可执行；观察任何结果后改冻结参数（包括"调题目措辞过校验"）都是违规，唯一正路是新一轮预注册+已见题转 seen_bucket 剔除主指标。