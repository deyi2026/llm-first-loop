---
method_id: resolve-task-reads-against-declared-worktree-anchor-2f6b658a0503
name: resolve-task-reads-against-declared-worktree-anchor
description: 任务书已声明 git worktree 锚点（工作树根＋HEAD）、且回执 cwd 在其中时，任务点名的已提交接口文件必须按该锚点根解析读取；读取工具的相对路径或主仓绝对路径解析到的是另一棵树，miss 不代表文件缺失。读 miss 的第一未知量是『这次读取解析到了哪棵树』：用一次成员判定（在声明的 HEAD 上列出文件清单按词根过滤）区分『锚点/路径失配』与『分支真缺失』——命中则换锚点根绝对路径重读，未命中则停止路径枚举、如实上报或求证。既避免在错误锚点下连续猜路径浪费多轮，也避免混用两棵树的接口签名导致实现绑错版本。
aliases: 读文件报不存在但代码明明在分支里, 相对路径落到别的目录去了, 双副本环境打开源码失败, 先确认文件是否已提交在当前分支, 从任务书定位基准目录再读取, file exists on branch but read fails
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:dc9cbbb4-590e-40e1-b360-158e5ef5619b:968:609bd23ff6697da79a1c
evidence_refs: learning:learn:48f172870ba8
created_at: 2026-11-19T21:12:33.352520+08:00
updated_at: 2026-11-19T21:12:33.352520+08:00
---
## Trigger
任务指令或同批回执已声明工作树锚点（命名的 .worktrees/… 根＋HEAD，或 shell 回执 cwd 位于其中），随后对任务点名的已提交文件做 read/inspect 却返回『路径不存在/文件不存在』。

## Discriminator
miss 发生前已有两条可用事实：① 指令行明确写出 worktree 根与 HEAD；② 最新 shell 回执的 cwd 就在该工作树内。二者共同锁定唯一合法读取锚点——凡未按 <锚点根>/ 绝对路径发出的读取，首选假设是解析到了主树，而不是文件真的不存在。

## Short path
- 从任务书提取锚点（工作树根＋HEAD），与最新 shell 回执 cwd 交叉确认，得到唯一读取根 <worktree-root>。
- 任务点名的每个接口文件直接以 <worktree-root>/… 绝对路径读取，一次拿齐签名/常量/复用点。
- 若仍 miss，先做一次成员判定：git ls-tree -r <声明的HEAD> --name-only 按词根过滤。命中＝锚点或拼写问题；未命中＝分支真缺失。
- 命中但读不到→检查读取工具的解析根或沙箱降级提示后重读；未命中→停止换路径枚举，如实上报缺失或向用户求证。
- 接口全部读齐且与任务书引用语义一致后，立即进入实现，不再重复核树。

## Stop conditions
- 任务书点名的全部接口文件已在锚点根下成功读取，内容与任务书引用的事实一致。
- 成员判定未命中：按『该分支确实没有此文件』收口并上报，不再换锚点或继续拼路径。

## Verification
- 锚点根内 git rev-parse HEAD 等于任务书声明的 HEAD。
- 成功读回执中的路径全部位于锚点根之下，且文件内容能对上任务书引用的行为/常量。

## Counterexamples
- 任务未声明任何 worktree、cwd 就是主 checkout：读 miss 应先按真缺失/未合并分支处理，在主 HEAD 上做一次成员判定未命中即收口，不要去找别的树。
- 用户明确要求检查主树或 main 上的状态（如核对已部署内容）：主树路径就是正确锚点，切换锚点反而读错对象。
- 目标在 checkout 之外的运行态（/private/var/run、/tmp 等）：不存在树锚点问题，直接绝对路径读取或按权限失败处理。
- 文件在声明的 HEAD 之后才新增（锚点 checkout 过期）：切换锚点也读不到，需要刷新 checkout 而非在两棵树间枚举。
