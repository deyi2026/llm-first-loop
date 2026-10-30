---
method_id: rename-to-align-inverted-default-remote-with-fail-closed-gates-d4e369e79568
name: rename-to-align-inverted-default-remote-with-fail-closed-gates
description: 当默认名 remote（如 origin）指向遗留/归档仓、真上游藏在非默认 remote 名后时，持久解法是结构对齐而非加纪律：先用 URL 身份线+branch.<main>.remote 钉死名实反转；用 rev-list --count 确认遗留远端 main 是真上游的严格祖先（降级安全前提）、reflog 确认是否仍被误推；再用 remote rename 让默认名承载真上游，被降级 remote 配 no-push 哨兵 pushurl+skipDefaultUpdate，pre-push 按 URL 身份（非名字）拒绝；波及面只改活纪律文档，历史回执保持原名；提醒配置 per-clone 多 checkout 需分别落地。
aliases: 怕推错远程仓库, origin 指向旧仓库怎么封, 改 remote 名防止误推, 真上游不是 origin 怎么防呆, 封禁归档 remote, git 推错远端怎么配置防
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f02d0f78-2dee-4e98-8056-26c7c3042ab0:0:9c6b0895b43b2e51f634
evidence_refs: learning:learn:0ab1f328c66d
created_at: 2026-10-29T23:23:15.329756+08:00
updated_at: 2026-10-29T23:23:15.329756+08:00
---
## Trigger
用户问如何持久避免把某 remote 误当上游/误推，且 git remote -v 显示默认名 remote（如 origin）指向遗留或归档仓库，真上游在非默认 remote 名上（branch.<main>.remote 指向后者）

## Discriminator
第一次 remote -v 的 URL 身份线与 config 中 branch.<main>.remote 已共同判定名实反转；rev-list --left-right --count <遗留>/main...<上游>/main 得 0/N（严格祖先）构成降级安全前提；refs/remotes/<遗留>/main@{时间}: update by push 证明仍有人在推遗留远端，闸不可省。

## Short path
- 一条命令钉反转：remote -v 身份线 + branch.<main>.remote + push.default/remote.pushDefault，不靠名字或记忆推断权威远端
- 安全前提验证：祖先计数确认遗留 main 是真上游严格祖先（可安全降级）；reflog 看遗留远端最后更新时间与来源，判定 fail-closed 闸是否仍必要
- 清点现有防护面：core.hooksPath、pre-push 实际内容、书面纪律行，列出仍无防护的入口（默认 push、fetch --all、GUI 合并基线）
- 结构修复：remote rename 让默认名承载真上游语义；被降级 remote 配 no-push 哨兵 pushurl + skipDefaultUpdate；pre-push 增加 URL 身份级拒绝段——配置层闸不可被 --no-verify/GUI 绕过，钩子层负责人话提示，两者互补
- 波及面切割：只重写活纪律文档（发版清单/重启指南），data/methods、governance 回执类历史证据保持旧名逐字不动，禁止批量改写
- 闭体验证并声明范围：upstream 解析、祖先计数、push --dry-run 回执目标 URL 三项对齐即停；提醒 remote 配置 per-clone，其他 checkout 需分别执行

## Stop conditions
- 闭项（remote 身份、main@{upstream} 解析、祖先计数、dry-run 目标 URL）全部符合预期，且改动面仅限配置+一段钩子+活纪律文档
- 用户只要一次性安全推送指引而非持久治理——直接给显式 `git push <真上游> <分支>` 即止，不做改名手术

## Verification
- git rev-parse --abbrev-ref main@{upstream} 解析为新权威远端
- git push --dry-run origin main 的回执目标 URL 是真上游仓库而非遗留仓
- 误推被降级 remote 时，即使带 --no-verify 仍被哨兵 pushurl 拦截（证明配置层闸独立于钩子生效）
- grep 确认活纪律文档无『origin=遗留』旧口径残留，同时历史回执文件未被改动

## Counterexamples
- 其他工具或脚本硬绑定非默认 remote 名时，rename 会破坏它们——退回最小解除（remote.pushDefault + skipDefaultUpdate + 修 GUI 基线），显式 push 仍需点名
- origin 本就是真上游、无名实反转——无需任何改造，常规显式 ref 纪律即可
- 只需这一次安全推送、不追求持久防呆——结构修复属过度工程
- 多 clone 多机器协作下本地改名不传播，若无文档/初始化脚本配套，其他 checkout 仍裸奔，此时方案必须落在 setup 脚本而非单次本地配置
