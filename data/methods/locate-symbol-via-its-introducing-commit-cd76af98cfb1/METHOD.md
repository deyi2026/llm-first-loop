---
method_id: locate-symbol-via-its-introducing-commit-cd76af98cfb1
name: locate-symbol-via-its-introducing-commit
description: 当某符号/文件的位置待定位，而已获取的回执（git log、事件流、部署状态）中已出现引入或修改它的具体 commit 时，先用一次 `git show --stat <引入commit>` 直接读出文件路径，再读该文件验证；不要先猜测目录布局，也不要直接发起全仓宽 grep。这把'在整个文件系统中枚举候选位置'压缩成'从已有因果记录中读出一个确定的下一跳'。若回执中没有引入 commit、可见 commit 只是提及符号而非定义处、或它是巨型 merge，则不适用，退回有界搜索。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:e8e83cd1-6d33-4a6b-b29b-56131638f5d7:334:8a61e51712488117066e
evidence_refs: learning:learn:20aa811c5bab
created_at: 2026-09-18T19:22:49.476448+00:00
updated_at: 2026-09-18T19:22:49.476448+00:00
---
## Trigger
需要定位某符号/文件（新组件、新路由、新测试）在仓库中的位置，且手头已获取的记录（git log、事件流、回执）中已出现引入或修改它的 commit/条目。

## Discriminator
进入任何文件系统搜索之前，上下文中的 git log 回执已明确列出引入 commit：`06552a114 fix(web): TASK-005 add missing ServicesPanel component`——该 commit 的 --stat 确定性地给出组件文件路径。这是定位动作发生前已可见的事实，不是事后倒推。

## Short path
- 明确未知量：'目标符号定义在哪个文件'（本例 ServicesPanel）。
- 检查手头已获取记录：git log 已列出引入 commit `06552a114 fix(web): TASK-005 add missing ServicesPanel component`。
- 执行一次 `git show --stat 06552a114`，直接得到 `webui/src/components/services/ServicesPanel.tsx`。
- read_file 该文件，确认符号定义与数据源（fetchServicesStatus → /api/v1/services/status），定位完成。
- 仅当第 2 步找不到引入 commit 时，才退回有界 search_files（先在 git 输出提示的顶层目录内，再全仓），避免无界 grep 超时。

## Stop conditions
- `git show --stat` 给出候选文件路径后立即停止搜索，转入读文件验证。
- 文件内容确认目标符号定义及其数据源/依赖后，停止发现，进入下游验证（本例：端口、路由鉴权、测试回执）。

## Verification
- 路径必须来自引入 commit 的 --stat 而非猜测目录；读文件后必须实际看到目标符号定义（如 export function ServicesPanel）才算定位成功，否则回到搜索分支。
- 任何'成功/失败'结论必须来自决定性回执行（passed/failed 行或完整 traceback），不能由截断输出或管道尾命令的退出码推断（本例 pytest 首跑 exit 0 实为 tail 的退出码，且被截断的 ERROR 恰是关键信息）。

## Counterexamples
- 手头记录中没有该符号的引入 commit（外部库、生成代码、log 未覆盖）→ 方法无输入，直接用有界 search_files。
- 可见的 commit 只是提及/适配符号而非定义处（如本例 `1103a7493` 只改测试文件，不含组件本体）→ 选错 commit 会得到无关文件，必须选'引入定义'的 commit。
- 目标是'行为是否生效'而非'代码在哪'：git 记录不能替代运行时验证（本例仍需项目 venv 下 pytest 7 passed 与 API 401 回执来证实路由注册与鉴权生效）。
- 引入点是巨型 merge commit、--stat 文件数过多时，按路径过滤或直接搜索反而更快。
