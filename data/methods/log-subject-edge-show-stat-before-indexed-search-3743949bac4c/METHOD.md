---
method_id: log-subject-edge-show-stat-before-indexed-search-3743949bac4c
name: log-subject-edge-show-stat-before-indexed-search
description: 在 git 仓库定位某构件（工具/脚本/入口）时，若早前回执的 git log 主题已点名其引入提交（feat/merge/fix subject 含构件名），把该提交当作 provenance edge：用 git log --grep（或直接 show 已见 hash）+ git show --stat 取权威文件清单锁定入口，再读其头部自述获取语义与边界；不要先做文件名/内容搜索——索引外路径（scripts/、docs/ 等）会静默 no-match，同域第二次换 pattern 重试是纯浪费。本集两次 search_files 无命中后，靠一次 git show --stat 直接命中入口脚本。与『用早前路径样例推导目标路径』不同：这里的边是提交主题→提交文件清单。适用：引入在可见 log 窗口内且仓库有 .git；不适用：找调用点、深历史构件、无历史快照树。
aliases: log 里点名了还满仓库搜, 找不到脚本入口先看引入提交, search_files 搜不到 scripts 怎么办, git show --stat 当文件清单用, 提交主题就是定位线索
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:2ef924ad-22aa-459c-881a-b100534b16c2:345:ebe50ad001924c836ecf
evidence_refs: learning:learn:74046a0d0695
created_at: 2026-10-29T13:45:44.185109+08:00
updated_at: 2026-10-29T13:45:44.185109+08:00
---
## Trigger
需要在仓库里定位某构件（脚本/工具/入口文件）的实现位置或行为语义，而早前同一会话的 git log 回执里已出现点名该构件的提交主题（feat/merge/fix subject 含其名字），或文件名/内容搜索已一次 no-match

## Discriminator
已握回执中的判别事实：log 主题直接命名构件并指向其引入/演进提交（如 merge 主题写明『某工具并入 main』、fix 主题已描述其行为边界），这条 provenance edge 比任何文件搜索更窄且不会漏；而同一搜索工具的 no-match 回执本身证明其索引不覆盖目标路径（scripts/、docs/ 类目录）

## Short path
- 把早前 log 回执里的点名提交当作边：git log --oneline --grep=<构件名>（或直接 show 已见 hash）取引入提交号
- git show --stat <引入提交> 取权威文件清单，从中锁定入口文件（可执行脚本 + tests + 接线文件）
- 读入口文件头部自述（docstring/用法段）回答当前语义未知量：作用 pathspec、副作用边界、退出码
- stat 命中的文件先确认在 HEAD 仍存在（防引入后改名/移动），再读
- 按语义执行，用执行回执（hash/数量）与脚本自述范围对账

## Stop conditions
- 入口文件自述已回答当初的语义未知量（范围/边界/退出码）即停止定位，不必再读 tests 或做补充搜索
- 同一搜索域两次 no-match 即放弃该 source class 改走历史边，不得第三次仅换 pattern 重试

## Verification
- git show --stat 清单中的入口文件在 HEAD 仍存在，且其 docstring 与 log 主题声称的行为一致
- 执行回执（提交内容/数量）与入口自述声明的作用范围一致

## Counterexamples
- 需要的是某符号当前全部调用点/使用图：commit stat 只反映引入时刻的文件集，grep/引用搜索仍是正解
- 构件引入早于可见 log 窗口（深历史）：应改用 git log -S<pickaxe> 或路径限定 log，而不是翻页读更多 log 或继续文件搜索
- 在无 .git 的导出快照/镜像树（如发布 release 目录）里：历史边不存在，退回文件系统枚举与搜索
- log 主题提到的入口此后被改名或拆分：stat 命中后必须先验证文件在 HEAD 存在再读，否则拿到的是过期位置
