---
method_id: branch-scoped-push-binding-resolution-over-bare-git-push-probe-44e6d87bdce4
name: branch-scoped-push-binding-resolution-over-bare-git-push-probe
description: remote 改名或 branch.*.remote 变更后，验证『默认推送落到哪个远端』时不要用裸 git push --dry-run 当探针：它按当前 HEAD 解析，把 HEAD 状态、钩子执行、绑定解析三个未知量耦合，detached HEAD 下必 exit 128，失败与 branch.*.remote 无关，极易误归因于本次改动；且 dry-run 的 To <url> 与 old..new 行和真实推送成功回执字节级相似（实为模拟输出），截断输出的尾部建议语不构成结论。改用与 HEAD 解耦的分支限定解析：rev-parse --abbrev-ref <branch>@{push} 加 remote get-url --push 钉 URL 身份，零副作用、不触发钩子与推送门禁横幅。
aliases: 改名后默认推送指向谁怎么验, git push dry-run 报 not currently on a branch 是不是 remote 配错了, dry-run 输出里的 To 行算不算真推送, 分离头指针下验证推送目标, 裸 push 失败先查 HEAD 还是查远端配置
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f02d0f78-2dee-4e98-8056-26c7c3042ab0:17:49c9e5f7273e6ce4f132
evidence_refs: learning:learn:0a96edad157f
created_at: 2026-10-29T23:33:07.396713+08:00
updated_at: 2026-10-29T23:33:07.396713+08:00
---
## Trigger
remote 改名或 branch.<name>.remote/pushDefault 变更后，需要验证某分支（如 main）默认推送目标是否指向正确上游，且近期回执未确立当前 HEAD 位于该分支

## Discriminator
待验事实是分支级绑定（branch.<name>.remote / <branch>@{push}），而裸 git push 是 HEAD 级探针，两者只在 HEAD 恰好位于该分支时等价；回执中没有『当前在目标分支』的坐标事实时，裸 push 的成败都回答不了绑定问题。输出若出现 detached-HEAD 建议语片段或 fatal: not currently on a branch，指向 HEAD 状态而非 remote 配置

## Short path
- 把待验未知量写成分支级问题：main 的默认推送目标是哪个 remote/ref
- git rev-parse --abbrev-ref main@{push}（必要时 @{upstream}）得到目标 remote
- git remote get-url --push <该 remote> 取 push URL，按 URL 身份线（非名字）比对期望上游
- 一致即闭合；若途中发现 HEAD detached，作为独立既有状态单独上报，不与绑定结论混同
- 只有待验问题本身是 HEAD 敏感行为或钩子行为时才用 dry-run，判据取退出码+全量 stderr，并把 To/old..new 行视为模拟输出

## Stop conditions
- @{push} 与 @{upstream} 解析到同一 remote 且其 push URL 身份与预期上游一致，即停止验证
- dry-run 输出尾部出现分支建议语或 exit 128 时，先定性 HEAD 状态，不再追加推送类探针

## Verification
- rev-parse main@{push} 与 git config branch.main.remote 指向一致，且 remote get-url --push 的 URL 身份线正确
- 对 dry-run 只依据退出码与 stderr 首行 fatal 文本下结论，不据尾部建议语

## Counterexamples
- 待验问题就是『在这个工作区裸敲 git push 会发生什么』：dry-run 的 exit 128 + fatal 本身就是答案，改用配置解析反而回避了真问题
- 需要实测 pre-push 钩子链（安全扫描 range、拒推守卫）时，dry-run 会真正执行钩子，是正确工具
- 单 remote 且 HEAD 明确在目标分支的仓库里，裸 dry-run 与分支限定解析等价，无需额外步骤
