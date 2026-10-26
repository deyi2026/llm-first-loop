---
title: 子代理 provider 投影熔断（active_run_ingress_unexpected_marker）：与模型无关，落盘优先+强制短输出的分段降级法
scenario: "需要独立子代理对文稿/代码/取证做审查并出具 PASS 结论，但子代理连续熔断（LLMProjectionError: active_run_ingress_unexpected_marker），无法拿到回执。"
root_cause: ""
solution: 不要重派整段或换模型（无效）。改为：①把任务切成极小分段并写 byte-exact 机械任务书；②强制子代理最终回复只写 1–3 行固定格式，长内容全部落盘到文件；③先机械取证落盘、再让裁决子代理只读证据文件裁决（避免长输出）；④父级只做合并与最终回执落盘，不替代独立判断。熔断后先检查子代理已落盘的产物是否存活，能复用就不要重跑。
evidence: "2026-10-20 实际运行：4 次子代理熔断（subagent_da867be8818e / aab9b4261bb4 / 1f461b483fdf / 2b29f685b9e0），错误均为 LLMProjectionError: active_run_ingress_unexpected_marker；分段重派后 subagent_9f52bac0de85（3 轮 858 tokens）成功产出 SEG1 证据、subagent_facdd581e156 成功产出 SEG2B、subagent_443977cbac0d（6 轮 3452 tokens）成功产出 PASS 回执。熔断后 seg2a_p1.txt、review_seg2b.json、review_verdict_B2.json 均存活。DSH 失败诊断见 data/dsh-home/logs/startup-2026-10-20T08-06-37*.log（$.provider missing required value）。"
tags: [subagent, provider, fusion, degradation, review-gate, orchestration]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-20T16:31:51.788697+08:00"
updated_at: "2026-10-20T16:31:51.788697+08:00"
supersedes: [EXPERIENCE-20261019-审稿子代理连环投影熔断时-停止换模型重试-发表闸门改走-review-admission-host]
---

场景：父会话需要独立子代理出具审查/核验结论，spawn_subagent 连续多次在 9 轮左右熔断，错误恒为 LLMProjectionError: provider projection failed structural validation: active_run_ingress_unexpected_marker。

## 观察到的模式（2026-10-20 实跑 4 次）
- 熔断与**模型无关**：MiniMax-M3.1-Flash-Preview 与 glm-5.3 都熔断在同一投影校验。
- 熔断点在**最终长输出**的投影阶段：失败子代理 tokens_out 达 8k–15k；而成功子代理 tokens_out 仅 858–3452。证据齐备但输出过长的段最容易熔断。
- 熔断发生时，**子代理已落盘的产物仍在**（例：/tmp/seg2a_p1.txt、/tmp/review_seg2b.json、/tmp/review_verdict_B2.json 都在熔断后存活）。所以"子代理 failed"≠"取证丢失"。

## 有效规避（已验证）
1. **把大任务切成极小分段**，每段任务书写成 byte-exact 机械步骤（"执行这一条命令，把结果写入 X 文件"），不让子代理自主调查。
2. **强制短输出**：明确要求最终回复只写 1–3 行固定格式（SEG1/VERDICT_A/NARROW2 等），把长内容全部导向文件。成功案例：3 轮、858 tokens。
3. **分段取证 + 分段裁决**：先让机械子代理把网页正文写盘（每个 URL 最多 1 次尝试，失败写 FETCH_FAIL），再让裁决子代理只读证据文件做判断——裁决者不接触长网页正文，输出量骤降。
4. **父级兜底合并**：父级只做分段产物合并与最终落盘，不吞掉子代理的独立判断。

## 无效尝试
- 换模型重派整段任务：同样 9 轮熔断，浪费一轮预算。
- 直接给裁决子代理塞「读稿件 + 读长证据 json + 写裁决 + 输出摘要」：输出量过大即熔断（15k tokens）。
- DSH 通道：data/dsh-home/profiles/headless/cordis.patch.yml 里 llm-pi-ai 的 glm provider 用 apiKeyEnv: GLM_API_KEY，而该 env 在本会话 shell 未注入（LLM_API_KEY 也为空，key 由外部环境注入到 web 进程），DSH 启动即报 "$.provider missing required value" 失败。要用 DSH 得先把 key 注入到 DSH 进程环境。

## 结论
子代理熔断是**输出投影层**故障，不是任务逻辑故障。降级方向是"缩输出、缩任务、落盘优先"，而不是换模型或重派整段。