---
title: dsh_task reasoning_effort 触发 config 浅覆盖导致 provider 丢失
scenario: "用 dsh_task（或 dsh CLI --patch）为子代理设置 reasoning_effort（low/medium/high/max）以控制推理预算时，任务在 0.4-0.8s 立即失败，报 \"agent-default-model: $.provider missing\" 或 \"model 'glm-5.3' does not support reasoning effort 'low'\"。"
root_cause: cordis 的 id-targeted patch 对 config 做整体替换（浅覆盖），而 dsh_task 的 reasoning_effort patch 只提交 reasoningEffort 一个键，导致同 id 下 profile 已配置的 provider/model 被删除。
solution: |
  根因：cordis 的 id-targeted patch 是整体替换 config，而非深合并。dsh_task 的 effort patch 只写 config.reasoningEffort，把 profile 里已配置的 provider/model 冲掉了。
  
  绕过方法（三选一）：
  1. dsh CLI 直调：在自己的 --patch 文件里把 provider/model 与 reasoningEffort 一起重声明：
     - id: agent-default-model
       config: {provider: glm-coding, model: glm-5.3, reasoningEffort: low}
     - id: llm-pi-ai
       config: {providers: {glm-coding: {... models: [{id: glm-5.3, reasoningEfforts: {low: low, high: high, max: max}}]}}}
     注意：若目标 model 未声明 reasoningEfforts，需在 llm-pi-ai patch 里补声明，否则报 "does not support reasoning effort"。
  2. 修 dsh_task.py：effort 合并进 config['providers'] 后再整体 patch（对应 dsh_task.py 415 行附近的 patch 构造）。
  3. 改 cordis patch 语义为深合并（影响面大，需评估）。
  
  另外：API key 通常未 export 到 agent shell，需 `set -a; . ./.env; set +a` 显式注入，否则报 credential 未配置。
  诊断手段：`dsh --profile headless --patch <f> --dump-config` 看合成后的最终 config，是定位此类问题最快的办法。
evidence: "--dump-config 合成结果显示 agent-default-model 的 config 仅剩 reasoningEffort: low，provider/model 消失；补齐 provider/model 后带 effort 的任务成功运行（85s 完成真实文件读取任务）。"
tags: [dsh, reasoning_effort, config-patch, 子代理, 推理预算, 环境bug]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-18T01:31:35.687942+08:00"
updated_at: "2026-10-18T01:31:35.687942+08:00"
---