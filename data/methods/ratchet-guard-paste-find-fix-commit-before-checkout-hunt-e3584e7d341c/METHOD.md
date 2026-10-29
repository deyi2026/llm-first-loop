---
method_id: ratchet-guard-paste-find-fix-commit-before-checkout-hunt-e3584e7d341c
name: ratchet-guard-paste-find-fix-commit-before-checkout-hunt
description: 用户粘贴守卫类测试失败（baseline 棘轮/单向门/配额登记断言）却未说明出自哪个检出、且本地有多个共享历史的克隆/worktree 时，第一个未知量不是'哪个目录跑了测试'而是'共享 git 历史里是否已有登记/修复提交'。断言正文通常自述补救机制并给出 file|symbol 精确锚点，一次全分支 git log 搜 baseline 文件与符号即可判定'检出落后于登记提交' vs '新代码未登记'；检出身份识别降级为用户侧一条 ancestry 自检命令。避免按 mtime 逐仓嗅探 pytest 缓存、在错误仓重跑守卫。
aliases: 棘轮守卫失败不知道哪个仓跑的, baseline 登记测试红了先找修复提交, 粘贴的守卫失败找不到来源检出, 单向门测试失败是漏登记还是新代码, 多个 worktree 里定位测试失败属于哪个检出
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ce8b88af-7349-4903-91ab-b37a329e0489:1057:5de8b63905ee0a89b4ea
evidence_refs: learning:learn:d79db9dc6a0f
created_at: 2026-10-29T01:13:44.924270+08:00
updated_at: 2026-10-29T01:13:44.924270+08:00
---
## Trigger
用户粘贴的测试失败来自守卫类断言（棘轮/baseline 登记/单向门/配额上限），未给出运行目录，环境中存在多个可能共享 git 历史的克隆/worktree/mirror，需要给出诊断与处置

## Discriminator
断言正文自述补救机制并给出精确锚点（如'新增/扩大，需显式审查 baseline：src/xx.py|_func_d...'，符号被截断可在任一含该守卫的仓 grep 源码补全）；且粘贴汇总行（N failed, M passed, K skipped）构成可匹配/排除检出的指纹。两种可能世界（检出缺登记提交 / 新代码未登记）用一次 git log --all 搜 baseline fixture 与违规符号即可区分，无需先确定运行检出。

## Short path
- 从粘贴文本提取锚点：守卫测试名、违规 file|symbol（截断则在任一含该守卫的仓 grep 补全）、补救机制文本（登记/审查 baseline）→ 假设：棘轮失败 = 检出缺登记提交 或 未登记新代码
- 在最近活跃/主 mirror 仓执行 git log --all --oneline -- <baseline fixture 路径> 与 git log --all -S"<符号>" -- <源文件>，定位登记或引入提交
- 找到登记提交 → 在含该提交的检出上跑守卫测试或用同款扫描器静态复现断言确认全绿；在其父提交确认复现与粘贴完全一致的失败节点与签名
- 交付：修复提交 id/分支 + 让用户在其实际检出跑 git merge-base --is-ancestor <fix> HEAD 自检；检出身份识别变为用户侧可选步骤，停止仓库枚举
- 若全分支搜不到登记提交 → 转入'新代码未登记'分支：在最新检出按守卫要求的审查格式做登记，而非继续找旧检出

## Stop conditions
- 已找到登记/修复提交，且验证：含它的检出守卫全绿、其父提交复现与粘贴一致的失败 → 交付自检命令并停止
- git log --all 搜 baseline 文件与符号均无登记提交 → 判定为未登记新代码，转入登记/审查流程，停止检出枚举
- 按指纹（lastfailed 内容、测试总数、缓存 mtime）排查 2~3 个候选检出均不匹配 → 停止枚举：失败运行可能来自已删除或无缓存的克隆，身份识别交还用户

## Verification
- 含修复提交的检出上，守卫测试（或同款静态扫描器+baseline）复现全部断言为绿
- 修复提交的父提交上重跑守卫，失败节点与违规签名与用户粘贴逐字一致
- 用户侧 git merge-base --is-ancestor <fix> HEAD 可在其真实检出独立复核结论

## Counterexamples
- 普通断言/回归失败（非 baseline/棘轮类守卫）：断言不自述登记补救机制，应按失败签名分诊——先跑失败用例、追实现与近期提交，不适用'搜登记提交'路径
- 用户明确要求'查出是哪个目录运行的'且身份本身即交付物：测试总数指纹、lastfailed 内容、缓存 mtime 匹配是正确工具，检出枚举正当，不应跳过
- 各克隆分属不同 fork、无共享 git 历史：在一个仓找到的登记提交不能迁移结论，须先确认分支/remote 同源
