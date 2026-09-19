---
method_id: repo-owned-qualification-harness-first-cd229cd17718
name: repo-owned-qualification-harness-first
description: 当用户要求测试某个内部缩写/命名的能力（如 'smc 操控浏览器'）时：先用一次 records/方法卡检索或一次定向文件搜索把术语落到具体工具与入口；若仓库自带以该能力命名、角色明确为 live qualification/acceptance 的可执行脚本，则把它当权威测试线——读其 docstring 与退出码契约、核对环境前置、带 evidence 目录运行并按断言计数验证。不要反复宽枚举同名文件、也不要深读与被测能力无关的 harness 治理文档（如 repeat-diagnostic 协议）。报告时必须声明覆盖边界（工具层端到端 vs 模型在环），不越界宣称。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:265:a628b20456a7558d3325
evidence_refs: learning:learn:ed874cadaefb
created_at: 2026-09-18T02:24:37.112930+00:00
updated_at: 2026-09-18T02:24:37.112930+00:00
---
## Trigger
用户要求测试/演示/验证一个缩写或内部命名的能力，且该术语在当前仓库或记录系统中有实体（方法卡、evals、qualification 脚本等）

## Discriminator
首轮检索已暴露与能力同名、角色可判读为 'live qualification/acceptance/smoke' 的可执行入口脚本（本例 step2 输出中已出现 scripts/qualification/smc_browser_live_*.py）；同时 search_records 存在 status=active 的方法卡直接点名具体工具。这两个当时可见的事实即可把『怎么算测过』从自行拼演示/枚举全部协议版本缩为『读契约并运行该脚本』

## Short path
- 未知量=术语指什么：先 search_records/方法卡一次，把能力名落到具体工具与调用循环（如 browser_perceive→browser_semantic_execute）
- 未知量=能否直接调用：查会话工具表/factory 注册，确认工具是否挂载；未挂载则改走仓库自带 harness 而非现场拼演示
- 未知量=合格线定义：只读对应 live qualification 脚本的 docstring+断言/退出码约定（如 'No model is called'、EXIT=0 全过）
- 未知量=环境是否满足：核对目标程序路径、venv、HEAD 等前置
- 执行：带 evidence-dir/result-json 运行脚本，验证退出码与 pass 计数=total
- 报告结果并声明已验证层级与未验证层级的边界

## Stop conditions
- qualification 脚本退出码 0 且各断言 pass 数等于 schema total，evidence 已落盘
- 术语无法落到任何方法卡或入口脚本（无 authoritative 命中）→ 停止套用，转而询问用户或自建最小测试
- 脚本契约显示其测试层级与用户意图不符（如用户要模型在环而脚本声明 No model is called）→ 改选/补做对应层级再交付

## Verification
- 退出码=0 且 behavior/safety 等断言 pass 数等于 total，result.json schema 与脚本声明一致
- evidence 目录真实落盘（actions/logs），关键安全断言（如 canary 全库检索为空）可在证据中复核
- 最终回答明确区分工具层验证与模型在环验证，未把前者说成后者

## Counterexamples
- 仓库只有库代码、没有任何 qualification harness：应自写最小测试/演示，而不是继续翻找不存在的入口脚本
- harness 在当前 HEAD 已坏（import 失败、引用已删除模块）：其权威性失效，需回退到自建最小验证并如实报告 harness 失效
- 用户明确要求模型亲自在环操作：no-model 的工具层 qualification 回答的是另一个问题，不能作为对该请求的直接交付
- 同名 harness 覆盖多个层级（unit / live / model-in-loop eval）：必须按用户意图选层级，跑错层级会静默答错问题
