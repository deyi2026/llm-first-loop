---
method_id: verify-defect-still-live-before-snapshot-premised-fix-work-156ed309f067
name: verify-defect-still-live-before-snapshot-premised-fix-work
description: 上轮审查/交接派生的修复-过审-推送任务，在多会话共享工作区续跑时，每个带标签动作都是对旧快照的前提断言；第一未知量不是『怎么修』而是『缺陷在当前版本面是否仍存在、推送是否仍需要』。判别事实：目标文件 git AM 态与新鲜 mtime、evidence 回执 freshness=stale（读取后被并发改写）、文件内引用 finding ID 的返修注释与专项测试即『已修复』的 artifact 自带 provenance；对推送前提，临时 worktree 自远端 cherry-pick 本地提交得空提交即内容⊆远端。前提已被满足则零改动闭环，不编辑并发会话在途文件；前提仍真才转入正常修复。与 pin-docs-vs-code-gap（裁决报告真伪）、concurrent-writer-divergence（发布钉死已验证提交）互补，本卡管执行侧的前提复核与免重复闭环。
aliases: 上轮报告要修的问题可能已被别的会话修好, 动手修bug前先确认缺陷还在不在当前版本, 共享工作区避免重复修复别人的在途工作, 旧审查单先对活代码核验再执行, push前先验证远端是否已包含本地提交, 空cherry-pick证明提交已在远端
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e827e946-e151-4ded-9bdf-58c042570992:84:56811d92283ebe126324
evidence_refs: learning:learn:154f224401e9
created_at: 2026-10-30T13:53:44.455265+08:00
updated_at: 2026-10-30T13:53:44.455265+08:00
---
## Trigger
续跑/受派任务按上一轮审查报告或交接快照执行带标签动作（修复某 finding、补测试、过审、push 指定提交），而目标文件位于多会话共享工作区并显示活跃并发编辑信号（staged-add+modified 状态、mtime 新于报告、evidence freshness=stale）

## Discriminator
任务前提是旧快照断言『缺陷存在/提交未推』，而活表面上已出现反向证据：当前版本目标文件含引用 finding ID 的返修注释与对应 guard 分支、测试文件含该 finding 标注的专项/参数化测试（artifact 自带修复 provenance）；evidence 回执 freshness=stale 证明两次读取之间有并发写入；git ahead/behind 与内容比对可直接算出推送前提真伪

## Short path
- git status/log 恢复现场：识别目标文件归属与活跃度（AM/M 态、mtime、ahead-of-remote 数），未知量=谁在改这棵树、我的推送范围是什么
- 直读活版本目标文件，搜索该 finding 的修复签名（返修注释、finding ID、对应判定分支），未知量=缺陷在当前版本面是否仍存在
- grep 测试文件中该 finding 标注的专项/参数化测试并运行该测试面，未知量=修复是否已带测试且当前全绿
- 残余失败按归属分流：属并发会话在途工作（如文案断言）则记录留置，不接手不阻塞闭环
- 对推送前提：临时 worktree 从 origin/main cherry-pick 本地提交，空提交=内容已含于远端，未知量=推送是否仍有必要
- 全部前提已满足即零改动收口，向用户报告任务形态变化（已由 owner 会话完成），全程不改并发会话在途文件

## Stop conditions
- 活版本已含修复签名且专项+参数化测试全绿，残余失败可明确归属为他人在途工作
- 对远端 cherry-pick 得空提交，证明本地提交内容⊆远端，无推送必要
- 无并发编辑信号且缺陷仍在当前版本面：前提成立，本方法终止，转入正常修复流程

## Verification
- 修复签名与 finding ID 注释逐字对应，且存在专项与参数化测试覆盖（非仅注释宣称）
- 前后 md5/version_token 对比确认自己未修改任何工作区文件
- 空 cherry-pick 加整文件 diff 仅剩远端新增段，证明本地内容逐字已在远端
- 暂存区/工作区状态收口后与并发会话原状一致，无幻影暂存残留

## Counterexamples
- 单会话仓库、status 干净且目标文件自报告后未动：报告前提可信，直接修复，不必先做 liveness 复核
- 活版本仅有注释宣称已修而无专项测试，或修复不完整：缺陷仍算存在，继续修复而非闭环
- 用户任务是只读裁决报告真伪（咨询『P1 是否属实』）：走版本面对齐的裁决方法，而非本卡的执行闭环
- finding 钉死在特定已提交 SHA 的历史评审基线上，不按 HEAD 活面判定是否已修
