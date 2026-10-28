---
method_id: pin-ref-owner-from-local-origin-before-dangling-claims-7fac94af74c3
name: pin-ref-owner-from-local-origin-before-dangling-claims
description: 多检出工作区（克隆、linked worktree、发布快照并存）里要判断『某具名提交挂在哪个分支/是否游离』时，不要 find .git 逐仓枚举再逐个 cat-file/branch --contains 试探。任务点名的部署检出里，remote -v 打印的本地 origin 路径就是 ref 拥有者，worktree list 进一步钉出共享主仓的检出集合；在拥有者仓库一次回答 ref 覆盖与祖先关系即可。下游克隆里 branch --contains 为空只说明本地分支不跨克隆可见，不构成『无 ref 游离提交』的证据——按克隆空结果下断言会产出错误结论（如本集上一轮的『游离提交』误判）并引发逐仓寻位探测。
aliases: 克隆查不到分支就问上游仓, 多个 git 检出找提交挂在哪, cherry-pick 前确认源提交有分支挂着, workspace 哪个仓库拥有分支, 别逐仓 find .git 找提交下落
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:659:f31289747b6d0ac73f19
evidence_refs: learning:learn:e27c0d834881
created_at: 2026-10-27T20:04:04.421949+08:00
updated_at: 2026-10-27T20:04:04.421949+08:00
---
## Trigger
工作区内同一项目存在多个 git 检出（克隆/worktree/快照目录并存），任务需要把具名提交接到部署或 push 线，或需要断言该提交的 ref 归属/是否游离

## Discriminator
进入任务点名的检出后，remote -v 已显示 origin 指向本地仓库路径（该路径即 ref 拥有者），且/或 worktree list 显示多个检出共享同一主仓；这条边在手时，任何单个下游克隆内 branch --contains/refs 为空都不是『游离提交』的证据

## Short path
- 只进入任务点名的部署/目标检出，一次读 remote -v + worktree list，钉死『这是克隆还是 worktree、哪个仓拥有分支』
- origin 为本地路径 ⇒ 直接在该主仓 for-each-ref --contains <sha>，一次回答源提交是否被 ref 锚定（cherry-pick 是否安全）
- 在主仓一次完成 merge-base/祖先判定，决定接入方式（ff/merge/cherry-pick），不逐克隆重复同问
- 后续走门禁流水线（审查→push→publish→restart），异步阶段按回执汇报『已受理≠完成』

## Stop conditions
- 拥有者仓 for-each-ref --contains 命中具体分支（或 fetch 后确认远端拥有）即停止寻位，不再枚举其他检出
- 祖先/接入方式已在主仓判定一次后，不再对每个克隆重复 merge-base 同问

## Verification
- 在 origin 指向的主仓运行 git for-each-ref --contains <sha>，非空即证提交被 ref 锚定
- cherry-pick -x 回执记录的源 sha 与源分支对账一致
- 主仓也为空时先 fetch 全部远端再判；仍空才允许『游离』结论并转为建 ref/导出补丁

## Counterexamples
- 单仓工作区：无拓扑可钉，直接本地 for-each-ref 与 merge-base 即可
- 提交确实只以对象形式存在于单个克隆（来自 bundle/patch），上游 fetch 后也没有：『游离』为真，应先建 ref 或导出补丁再移植
- 所有 remote 都指向外部托管（无本地路径 origin）且各检出互不相干：本地拥有者线索不存在，回到有界枚举
- 分支只在尚未 fetch 的远端上：不 fetch 就查本地 refs 会误判游离
