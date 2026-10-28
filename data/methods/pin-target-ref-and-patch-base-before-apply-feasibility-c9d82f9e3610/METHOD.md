---
method_id: pin-target-ref-and-patch-base-before-apply-feasibility-c9d82f9e3610
name: pin-target-ref-and-patch-base-before-apply-feasibility
description: 已过审候选 patch（或 worktree 内未提交差分）要落地合入、且仓库多 worktree 而主仓恰检出在无关 feature 分支时，不要对主仓当前检出树做 git apply --check 来判断可行性，更不要在失败后进入冲突诊断/三路合并/重导 patch 的绕路。先钉死两个 commit：patch 的基准提交（state.json/审计记录/worktree HEAD 已给出）与目标 ref（refs/heads/main）的实际位置；主仓 checkout 只是偶然状态。若基准==ref tip 且候选已以未提交差分存在于该 worktree，合入=就地提交+CAS update-ref，跨树 apply 既无必要也无意义。
aliases: patch 落不下去先查基准提交, 别拿主仓当前分支当合入目标, 先看 main 指向哪再试 apply, worktree 就地提交再推 main, update-ref 带旧值防并发误写
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:458:8caf233d30c3a0aee875
evidence_refs: learning:learn:a66f1bcb6082
created_at: 2026-10-27T18:13:09.574140+08:00
updated_at: 2026-10-27T18:13:09.574140+08:00
---
## Trigger
候选补丁或工作树差分已通过审查/门禁，需要决定合入路径；仓库存在多个工作副本，主仓检出在与集成目标无关的分支上；正准备做 apply/merge 可行性判断或比对『worktree 与主仓的提交关系』。

## Discriminator
patch 的基准提交早已由既有记录给出（state.json head、审计 md 的 pre-image、worktree HEAD 三者可互证）；目标 ref 的位置一次 rev-parse 即可钉死；而主仓工作副本当前检出的分支与目标 ref 无必然关系——apply-check 在那棵树上失败是问错了问题，不是 patch 本身有问题。

## Short path
- 先读状态/审计记录与 worktree status，钉死 patch 基准提交（如 worktree HEAD）
- rev-parse 目标 ref 并比较其与 patch 基准提交的关系——这是唯一决定合入方式的未知量
- 若基准==ref tip 且候选已是该 worktree 的未提交差分：按显式文件清单就地提交，CAS update-ref（带旧值校验）推进 ref，不做跨树 apply
- 主仓 checkout 在无关分支 ⇒ 仅记为『不要在该工作区直接 apply』的警示，不据此推断 patch 可行性
- 内容同一性用 blob 级比对 patch 后像，不靠 apply 退出码；写 .git 被沙箱拒绝时，输出用户可执行的收口命令并附实测证据

## Stop conditions
- patch 基准与目标 ref 位置均已钉死且关系明确（相等/祖先/分叉）
- 内容 blob 级一致已验证，提交与推进命令已交付或完成；不再对任何非目标树做 apply 试验

## Verification
- git rev-parse 目标 ref 与 patch 基准提交比对后再下合入结论，不以 merge-base+提交清单枚举替代
- 提交后 git show --stat HEAD 核对文件清单；update-ref 必须带 expected-old-value，失败即并发漂移，重查而非强推

## Counterexamples
- 目标 ref 确实停在 patch 基准的祖先（中间提交批次未进目标）⇒ 无法 fast-forward，此时对目标树做 apply-check/三路合并评估正是正确动作
- 候选只以 patch 文件存在、没有承载它的 worktree 工作树差分 ⇒ 必须在某棵树上 apply，『就地提交』捷径不存在
- 用户明确问『这个 patch 能否 apply 到当前检出分支』⇒ apply-check 就是被问的问题，不是绕路
- 单工作副本且 checkout 即目标分支 ⇒ checkout 状态即 ref 状态，但仍需防 detached/dirty 工作区误导
