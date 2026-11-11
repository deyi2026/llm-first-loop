---
method_id: ancestry-direction-splits-stale-cache-from-remote-drift-then-one-fetch-67152b74bdad
name: ancestry-direction-splits-stale-cache-from-remote-drift-then-one-fetch
description: 仓库 status 的 ahead/behind 或缓存的 origin sha 与预期/上次报告矛盾（如待推 5 个而用户只批准 4 个）时，先别定性为『事实漂移』再翻 reflog 考古。先用已在手的本地 HEAD 日志定位缓存 sha：它若严格位于上次已知已推送 sha 之下（为其祖先），唯一自洽解释就是本地 tracking ref 自那次 push 后没更新，真实待推数=已推..HEAD。对权威远端跑恰好一次 fetch 即可证实；只有 fetch 结果与该预测矛盾才升级为漂移调查。
aliases: behind 数比批准的多先查缓存旧不旧, origin 比昨天推的还旧就是缓存没更新, fetch 前别急着说远端漂了, 待推送提交数和批准的对不上, ahead behind 以 fetch 后为准
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:3334:87f140cd69daa1a7b0af
evidence_refs: learning:learn:dc9c2e77faf1
created_at: 2026-11-11T10:24:57.719979+08:00
updated_at: 2026-11-11T10:24:57.719979+08:00
---
## Trigger
本地与远端的比较结果（ahead/behind、缓存的 origin/main sha）与用户批准的计划或上次报告的已推状态出现矛盾——典型如待推送提交数比批准数多出恰好一段已知已推的历史

## Discriminator
缓存的远端 sha 已经出现在本轮回显的本地 HEAD 日志里、且严格位于上次已知已推送 sha 之下（为其祖先），behind 数恰好等于 tracking-ref..HEAD——远端前移不可能让缓存看起来更旧，故唯一解释是缓存过期而非远端漂移

## Short path
- status 输出发现 behind=N 与批准的 M 矛盾；先明确未知量：缓存过期还是远端真动了
- 在已回显的本地 HEAD 日志中定位缓存 origin/main sha：位于上次已推 sha 之下⇒预测缓存过期，真实待推=上次已推..HEAD，不必先向用户宣告漂移
- 对权威远端（按 URL 身份确认，多 remote 仓库排除镜像）执行恰好一次 fetch 核实 sha 与 ahead/behind
- fetch 结果符合预测即直接继续批准范围内的工作，不做漂移叙述、不挖 reflog
- fetch 矛盾（远端领先/分叉/被改写）才转入漂移与分叉处理

## Stop conditions
- fetch 后远端 sha 等于上次已知已推 sha，且 ahead/behind 等于用户批准的提交数——矛盾已消，按原计划执行
- fetch 显示远端确实前进、分叉或被改写——本卡前提被证伪，切换到漂移/分叉调查流程

## Verification
- fetch 后重算 ahead/behind，数字与批准计划一致后才把提交数当作事实报告给用户
- 多 remote 仓库确认 fetch 目标按 URL 身份是权威远端而非镜像（与『钉死权威远端再比较』类判断组合使用）

## Counterexamples
- 缓存 sha 不在本地历史中、或领先于 HEAD（远端有我们没有的提交/已分叉）——这是真实漂移，禁用本捷径
- 同一会话刚 push/fetch 更新过 tracking ref、计数仍矛盾——矛盾在别处（比较错了分支或错的 tracking ref），不是缓存过期
- 下一步动作若基于该计数且不可逆（force-push、reset 类）——即使祖先方向判定为缓存过期，也必须实际 fetch 确认，不可跳过核实
