---
method_id: isolated-worktree-ref-facts-via-ls-remote-split-preflight-by-locality-b13c79a4a7dc
name: isolated-worktree-ref-facts-via-ls-remote-split-preflight-by-locality
description: 新隔离 worktree 共享主仓库 .git 且被沙箱写围栏时，本地 ref 不可靠：未 fetch 的 tag 查找会 exit 128 中断 && 复核链，push 后 tracking ref 更新失败只是环境噪声。复核按数据所在地分组（本地 HEAD/porcelain、远端 ls-remote、CI 工件），ref 事实一律以 ls-remote 为权威；push 成功只看退出码+远端接受行，终验独立 ls-remote。
aliases: 新worktree里查tag本地报unknown revision, push成功但stderr报cannot lock ref, 复核命令链被本地tag失败打断, 隔离worktree的tag用ls-remote查, 沙箱拦住主仓库git refs更新, push后本地tracking ref没更新要紧吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bc99ff08-658c-4355-afd2-b4b2ecc29011:187:f942fe047601058fe225
evidence_refs: learning:learn:6a64338dd6e7
created_at: 2026-11-12T14:21:42.117885+08:00
updated_at: 2026-11-12T14:21:42.117885+08:00
---
## Trigger
在新建隔离 worktree（共享主 .git、写围栏沙箱）中执行 push 前只读复核或 push 后远端确认，且需核验 tag / remote-tracking ref 事实时

## Discriminator
worktree 为新建隔离（本地未 fetch tags，tag 查找会 unknown revision）且任务把受保护 tag 身份陈述为远端事实（对象 SHA+指向 commit）⇒ 本地 tag 查找既不必要也不可靠，ls-remote 才是权威探针；工具回执已标明沙箱仅允许写工作区 ⇒ 主 .git 内任何 ref 写（含 push 后更新 tracking ref）必被拦，属可预期环境行为

## Short path
- 复核前按数据所在地分组：本地仓库事实（HEAD/parent/porcelain/show --stat/numstat）一条链；远端 ref（ls-remote main + ls-remote tag）独立一条链，绝不混入本地 tag 查找；CI 工件（json 状态+log SHA256+尾行）再一条
- 组间不用 && 串联：任一组失败不中止其他独立检查，失败组单独补跑
- push 后先看退出码与远端接受行（old..new）：exit=0 且有远端更新行时，stderr 的 cannot lock refs/remotes/... 判为沙箱拦主 .git 写的环境噪声，不重试、不调试本地 ref
- 独立 ls-remote 确认远端 main 精确=拟推 SHA、受保护 tag 与授权给定值一致，落账即停

## Stop conditions
- ls-remote 显示远端 main=拟推精确 SHA 且受保护 tag 未变
- push exit≠0 或输出含 [remote rejected] ⇒ 真失败，停止并报告，不绕过不重试
- 远端权威值已确认后，仅剩本地 ref 类报错（unknown revision / cannot lock ref）不再追查

## Verification
- tag 身份只对照 ls-remote 输出与任务给定对象 SHA，不以本地查找为准
- push 成功判据=exit 0+远端 old..new 接受行，而非 stderr 无错
- 终验用独立 ls-remote refs/heads/main（及受保护 tag ref）逐字符比对

## Counterexamples
- 需验证 annotated tag 对象内容（tagger/消息/目标类型）时 ls-remote 不足，须在含该 tag 的仓库 cat-file -p tag
- 无沙箱的普通 clone 中 push 后 tracking ref 更新失败可能指示真实本地问题（陈旧 lock、权限），应排查而非忽略
- 任务要求本地 worktree 必须含 tag（如从 tag 构建/测试）时需先 fetch 到隔离 worktree 自身 refs，『不依赖本地 tag』不适用
