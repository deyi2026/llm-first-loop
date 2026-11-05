---
method_id: refactor-own-ratchet-violation-verify-in-guard-read-scope-e32da19c1b0d
name: refactor-own-ratchet-violation-verify-in-guard-read-scope
description: 提交面锚定的棘轮/基线守卫（函数行数、复杂度、覆盖率-vs-HEAD 等）读『HEAD+staged』，未暂存的工作树修改对它不可见。两条判据：守卫报红对象与自己最近提交的 +N 行 stat 吻合＝新引入违例，应重构压回阈值而非重生成基线当场豁免自己；修复经写后回执/diff/直读工作树的测试证明生效后守卫读数却逐字不变＝读源口径错位，git add 后重跑即恢复。避免『修复无效』误判与错误豁免两条歧路。
aliases: 改完守卫还报旧数字, 函数行数超标要不要重生成基线, 守卫读暂存还是工作区, git add 之后棘轮才认, 自己的提交把函数顶过线, 行数守卫没看到我的修改
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:1218:fa098a502feb08123844
evidence_refs: learning:learn:97b30bc3512b
created_at: 2026-11-05T18:25:04.367303+08:00
updated_at: 2026-11-05T18:25:04.367303+08:00
---
## Trigger
分层提交门禁链中的基线/棘轮类守卫报红，且报红点名的函数/文件命中自己最近一次提交的改动；或修复已确认生效后重跑守卫，仍得到与修复前逐字相同的旧读数

## Discriminator
两条当时即可见的事实：① 守卫错误里的函数/文件与自己最近 commit 的 +N 行 stat 吻合 → 违例是新引入的，脚本提示的 regen baseline／豁免前缀等于把新增违例当场免掉；② 修复已由写后回执/diff/直读工作树的测试证明生效，守卫读数却不变，且 git status --porcelain 显示该文件为 ' M'（未暂存）→ 守卫读的是提交面而非工作树

## Short path
- 守卫报红 → 对照最近提交的 stat：命中自己改动则判定为新引入违例，选重构（抽类/抽函数）把度量压回阈值，拒绝重生成基线/加豁免前缀
- 重构完成并以读工作树的手段（测试/diff）确认度量确实下降 → 查 porcelain 该文件是否 ' M' 未暂存
- 仅 git add 该文件，使守卫读源口径切到工作树 → 重跑守卫，读数应随 staged 内容更新并转绿
- 绿后走原闸流程（全量门禁 → 独立提交），全程基线/登记文件零改动

## Stop conditions
- staged 后守卫读数更新并转绿
- stat 对照证明违例属 legacy 基线内旧代码被阈值收紧波及 → 转正规登记/豁免流程，不做机械重构
- staging 后读数仍逐字不变 → 读源口径假设被证伪，转查守卫实现（缓存、读了别的树）

## Verification
- porcelain 状态从 ' M' 变为 'M ' 后重跑守卫，读数随之变化
- 最终提交 diff 中基线/登记文件零变更，证明走的是重构而非豁免
- 对将要提交的确切树跑全量门禁退出码 0

## Counterexamples
- 守卫本身直读工作树（ruff、pytest 等常规工具）——staging 不改变其结果，先怀疑读口径是浪费时间
- 违例是 legacy 基线内旧代码被全局阈值收紧波及——按流程登记豁免比机械重构旧代码风险更低
- 尚无任何证据证明修复生效就先查读口径——应先用读工作树的验证建立『改了但读数不变』的矛盾，再下口径结论
