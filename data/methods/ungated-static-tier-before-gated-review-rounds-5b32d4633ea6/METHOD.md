---
method_id: ungated-static-tier-before-gated-review-rounds-5b32d4633ea6
name: ungated-static-tier-before-gated-review-rounds
description: 把补丁送过分层门禁链（静态 ratchet→审查闸→全量测试）时，先用一条免闸的静态层命令验证「当前基线能否走到全量阶段」，再开昂贵的审查子代理轮次。多写者共享仓库里 HEAD 常带其他会话的未推提交，全树 ratchet 可能早已被与本次无关的旧文件破坏；晚到提交后才暴露，会让已烧掉的审查预算全部作废，并把本可提前并行化的用户修复决策拖到最后。
aliases: 先跑 ruff 再开审查闸, 提交前先确认基线 lint 是绿的, CI 卡在与本次无关的旧文件上怎么办, 门禁分层时先跑便宜的那层, 全量测试被 ruff ratchet 拦住, 开审查子代理前先验基线
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:1110:b3ace6ce00fdb1c790e9
evidence_refs: learning:learn:9e13ffb6a4d6
created_at: 2026-11-05T17:51:29.812804+08:00
updated_at: 2026-11-05T17:51:29.812804+08:00
---
## Trigger
任务要求按分层门禁流程落库/提交（静态检查层 → 独立审查闸 → 全量测试），且当前分支的基线健康未经本会话验证——如 main ahead>0、工作区有其他会话的 untracked 产物、门禁采用严格全树 ratchet（任何新 fingerprint 即拦）。

## Discriminator
门禁脚本头部（开闸前已读到）自述分层顺序与 fail-fast 语义：最便宜的一层是全树静态 ratchet、修改文件零红、新 fingerprint 直接拦；且该静态层不在审查闸保护范围（规则只拦“全量测试”，tier0/静态预检明确是开发回路）。同时 git status 显示 ahead>0 与外来会话产物——“基线是否还能走到全量阶段”是一个一条命令即可消解的未知量，而不是既定事实。

## Short path
- 读门禁脚本/合同头部，分清哪些层免审查闸、哪层最便宜最先执行、拦截语义是什么（新 fingerprint vs 修改文件零红）
- 开审查闸之前，先跑免闸静态层（ruff ratchet 或 --quick 预检），把「基线可达全量阶段」变成已验证事实
- 若被与本次无关的文件挡住：先机械归属——该文件工作树是否干净、哪个提交把违规带入 HEAD——不把修复吞进本次补丁，也不继续烧审查轮次
- 把归属结果与修复成本（一行 f-string、需独立走一次闸）立即呈报用户，让该决策与后续流程并行
- 静态层确认绿（或基线修复已另立闸次）后，在 untracked 已收敛的状态下开审查闸，提交后全量链一次通过
- 若静态层直接绿：照常进入审查闸，不额外重复验证

## Stop conditions
- 静态层绿：本会话已持有基线可达证据，停止基线探查，进入审查闸流程
- 静态层红且违规落在本次改动文件内：先修复重跑，未绿不得开闸
- 静态层红且归属为他人旧提交：停止消耗审查预算，呈报归属与修复成本，等用户裁决

## Verification
- 被挡文件 git status 干净 + log/blame 定位引入提交，证明违规非本次改动带入
- 本次改动文件 changed_file_diagnostics=0（自己的补丁零新增诊断）
- 最终全量链确实执行到 pytest 阶段并完成，而不是在第一层被拦后用定向测试替代背书

## Counterexamples
- 静态层本身也在审查闸保护范围内（该仓库规则要求任何 CI 步骤前先审）：不可前置跑，先读规则再定顺序
- 本会话已持有同一 HEAD 的绿回执（CI 刚过、ahead=0、单人仓库）：基线健康是给定事实，重跑属无信息重复
- 纯文档/无代码改动且静态层只覆盖代码文件：无需基线探查
- 门禁是单层全量脚本（无免闸的便宜层可前置）：没有可提前消解的未知量，本方法不适用
