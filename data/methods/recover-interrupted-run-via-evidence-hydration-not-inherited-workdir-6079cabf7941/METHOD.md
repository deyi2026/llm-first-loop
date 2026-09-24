---
method_id: recover-interrupted-run-via-evidence-hydration-not-inherited-workdir-6079cabf7941
name: recover-interrupted-run-via-evidence-hydration-not-inherited-workdir
description: 会话恢复（'继续'类指令）时，中断 run 的尾部 shell 参数（workdir/假设路径）只是未验证假设；该 run 中断前的成功观测（evidence refs：execute_command 回执、read_file、runtime 快照）才是权威地面真值。本集把中断 run 事件流里的 workdir /workspace/codearts-agent 当成事实，连出 2 次失败 cd + 多轮宽事件流翻页才找到真实根路径；而第一步 list_evidence 里就躺着上一 run 的 pwd&&ls 回执和关键文件 refs，一次 hydration 即可同时恢复结论全文与绝对路径。方法：先 hydrate 观测 refs，再做一次定向 git/worktree 验证，然后产出交付物。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fc0ed66c-e669-41c4-94d7-7e05031bbac6:61:6499da2affc5059e3de9
evidence_refs: learning:learn:373eaf983ebb
created_at: 2026-09-22T17:24:25.758946+00:00
updated_at: 2026-09-22T17:24:25.758946+00:00
---
## Trigger
恢复被中断的上一 run / 续跑会话，且 evidence store 中已存在该 run 中断前的成功观测 refs（execute_command 回执、read_file、runtime 快照），而工作目录/路径尚未经观测确证

## Discriminator
两事实同时在手：(a) list_evidence 第一步已返回中断前观测 refs——最新一条是上一 run 00:17:52 的 execute_command（pwd && ls）回执，read_file refs 亦可 hydrate，内容头含真实绝对根路径；(b) 错误路径 /workspace/codearts-agent 仅来自事件流中已中断 run 的 shell workdir 参数，该 run 本身已知'只做了目录探测'且被中断，其执行参数不是 provenance

## Short path
- list_evidence 定位上一 run 的 refs：未知量=中断前存在哪些成功观测（含最后的 pwd&&ls 回执）
- hydrate 该回执与最相关 refs（关键源码读取、runtime 快照、动作 JSON）：一次同时恢复实际 cwd/绝对根路径与待恢复结论全文（grill_me 草案、核验事实）
- 以恢复出的根路径执行一次定向验证命令（git worktree list / git log）：未知量=部署基线与分支状态（deploy worktree @ HEAD）
- 用恢复的草案+已核验事实组装交付物；当路径与结论均有观测来源支撑时停止

## Stop conditions
- 待恢复结论（草案/事实清单/回执）已从 evidence hydration 完整取得，无需再翻事件流
- 工作根路径已由中断前的观测记录（pwd/ls 回执或 read_file 内容头）确证，不再枚举候选路径

## Verification
- hydration 内容中的绝对路径与随后 git/worktree 命令实际执行成功一致
- 恢复内容的关键字段（action_id、deployment_generation、草案条目数）与最终交付物一一对应，无凭记忆补写

## Counterexamples
- 上一 run 未留下 evidence 记录或 refs 已过期/失效 → 恢复通道只剩事件流与目录探测，本方法不适用
- 事件流显示中断前最后一条命令已在该 workdir 成功执行（有成功回执）→ workdir 已被观测确证，可直接沿用，无需重新推导
- 全新任务而非会话恢复 → 不存在'待恢复的中断前观测'，不应套用
- evidence refs 只覆盖无关文件、不含 cwd 或关键结论 → hydration 后仍需事件流/目录发现补充
