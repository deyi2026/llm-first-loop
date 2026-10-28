---
method_id: preflight-full-file-sizes-against-downstream-gate-caps-before-closure-co-9b55b1b1a429
name: preflight-full-file-sizes-against-downstream-gate-caps-before-closure-commit
description: 为过『树必须干净』门而按仓库先例做机械收口提交前，先对将进入提交的每个文件做全尺寸预检：下游审查门的字节上限按完整文件内容计，而非 diff 大小。若超大文件的本地改动只是可再生的运行期刷新（时间戳等），直接还原到远端已推送版本使净变化归零，把它排除出提交与审查材料；权威改动才走拆分路线。历史先例通过≠现在可过（先例可能靠已被修复的门盲区通过）。门间结构性冲突提演进建议，不在流水线内死磕。预检把『提交→被拒→调查→重做一轮审查』压成一次通过。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:1260:d0eb1a0ca422d15602f3
evidence_refs: learning:learn:40c91670196e
created_at: 2026-10-21T19:35:03.052184+08:00
updated_at: 2026-10-21T19:35:03.052184+08:00
---
## Trigger
串联门发布流水线（commit→独立审查→push→publish）中，为满足门 A（如 publish 要求 tracked 树干净）需按历史先例把运行期工件整体机械提交，而下游门 B（push/publish 的审查准入）对审查材料有字节上限。

## Discriminator
初始 git status 回执已列出将进入提交的全部脏文件，每个文件的完整字节数一条 wc/ls 即可得；会话内每次 push 都必须过 review_admission 的事实已在先前回执中确立。判断口径是全文件尺寸而非 diff 尺寸——审查材料按 committed 文件全量组装（容量拒绝回执以 committed: 前缀点名最大文件及字节数）。

## Short path
- 机械提交前，对 git status 列出的待收口文件逐一取全尺寸（wc -c），识别是否存在单文件全量远超常见审查材料上限（如 ~200KB 量级）的文件；必要时先 grep 门实现里的上限常量。
- 对超限文件判改动性质：git diff 看内容——仅时间戳/可再生运行期刷新→非权威、可丢弃；真实内容→不可还原。
- 非权威超大文件：还原到 origin 已推送版本（净变化归零，使其不进入提交与审查材料），其余工件照先例机械提交（tracked-but-gitignored 更新用 git add -u）。
- 正常走审查→push→publish；若仍被容量拒绝且改动不可丢，转既有 gate-cap-rejection 卡：读门材料组装代码、按实测边界拆分提交。
- 确认两门约束互斥属结构性死锁时，止于演进提案交人工裁决，不在流水线内循环重试。

## Stop conditions
- 收口提交内全部文件全尺寸低于下游材料上限，或超限文件已还原至净变化为零。
- publish 绑定成功、tracked 树干净、本地与远端一致。
- 冲突被证实为结构性（门 A 强制提交运行期工件 vs 门 B 按全量计材料上限）后即止于演进提案。

## Verification
- review_admission 回执 qualification=PASS 且无容量类拒绝。
- git status 干净、main 与 origin/main 一致、publish 绑定的 git_head 为新 HEAD。
- 被排除文件与 origin/main 逐字节一致（git diff origin/main -- <file> 为空），且其被丢弃的改动确认可再生。

## Counterexamples
- 超大文件的本地改动是审查必须覆盖的真实权威内容（非时间戳刷新）：不可还原，应按 gate-cap-rejection 卡读门组装代码并拆分提交，使每次审查材料低于上限。
- 下游门不按全文件内容组装材料（仅按 diff 计或无字节上限）：全尺寸预检不必要，按先例直接提交即可。
- 无串联审查/publish 门的一次性本地提交：预检属过度开销。
