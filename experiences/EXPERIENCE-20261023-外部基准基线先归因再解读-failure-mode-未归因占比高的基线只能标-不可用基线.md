---
title: "外部基准基线先归因再解读：failure_mode 未归因占比高的基线只能标\"不可用基线\""
scenario: "用外部 agent 基准（Terminal-Bench / SWE-bench 等）产出一份 LFL harness 基线后，直接把该分数当作\"LFL 能力\"或\"与其它 harness 差距\"来解读与对外发布。"
root_cause: "把\"任务未解出\"与\"评测链路自身失败\"混为一谈：harness 侧的模型拒绝、工具报错、解析失败、超时被计入分母，等于用基础设施故障惩罚 agent，得到的分数既不能代表能力，也不能作为回归比较的锚。"
solution: "基线产出后先做 failure_mode 分布统计，再决定它能不能用：(1) 逐任务记录 failure_mode（unknown_agent_error / timeout / parse_error / unset 等）；(2) unknown_agent_error 占比 >30% 时该基线只能标\"不可用基线\"，禁止进入任何能力比较或对外结论；(3) 对未归因类抽样取证（每类≥10 例），区分模型拒绝 / 工具报错 / 解析失败 / 超时 / 环境，逐类修 harness 或登记 known-reds；(4) 归因完成后再重跑，得到可用基线；(5) 未判定任务必须补判或如实登记，不得留空。当前性验证：跑 `python3 -c \"import json,collections;d=json.load(open('eval/results/baseline_v0_terminus2_glm53_full/2026-10-14__20-23-44/results.json'));print(d['accuracy'],len(d['results']),collections.Counter(x.get('failure_mode') for x in d['results']))\"` 应得 0.0886 / 79 / unknown_agent_error=52（若该 run 已被重跑或归档，则以 `ls eval/results/baseline_v0_terminus2_glm53_full/` 下的最新 results.json 为准并重新登记）；另 `ls eval/baselines eval/rules` 应为空（基线文档与规则文档尚未落盘）。"
evidence: 2026-10-23 实测 eval/results/baseline_v0_terminus2_glm53_full/2026-10-14__20-23-44/results.json：accuracy=0.0886（7/79 判定），80 个任务目录中 path-tracing 无结果；failure_mode 分布 unknown_agent_error=52、test_timeout=9、unset=8、parse_error=5、agent_timeout=5 —— 即 68% 失败属未归因 agent 侧错误，该数字当时不可代表 LFL 能力。
tags: [评测基线, 失败归因, benchmark, Terminal-Bench, 诚实性]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-23T08:53:48.229466+08:00"
updated_at: "2026-10-23T08:53:48.229466+08:00"
---