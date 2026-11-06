---
method_id: disjoint-file-face-parallel-lanes-with-merge-tree-gates-on-moving-main-db3f508db834
name: disjoint-file-face-parallel-lanes-with-merge-tree-gates-on-moving-main
description: 多会话共享 main 的仓库里，按设计文档实施某一批次改动时：开工前先求两个文件面的交集——文档具名列出的本批实施文件清单 vs 另一会话在途 goal 的文件/主题面。交集为空才登记独立 lane 并行开发；非空或同主题则让位给『探测在途提交』路径。此后把 main 当移动目标：每次整合闸（merge/push）前用 merge-tree 复演零冲突并向对方发时序协调请求；对方推进 main 后只增量重验受影响面，不重跑全流程。可省去：试探性开工后合并撞车返工、每次 main 前进后全量重验。
aliases: 两个会话一起改同一个仓库怎么不打架, 并行开lane前先对一下各自动哪些文件, 别的会话一直在推进main我这边怎么安全合并, 多会话并行开发先做冲突预检, 同仓多会话分工避让与合并时机, 按设计文档分批实施时和并行会话怎么划界
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8ce6aa41-bb36-4a43-9e62-65b65cd6bd74:7:56be9c9f1dc33f49588b
evidence_refs: learning:learn:a9809d8b985f
created_at: 2026-11-06T15:18:58.537038+08:00
updated_at: 2026-11-06T15:18:58.537038+08:00
---
## Trigger
仓库有多会话并行（Task Frontier 或会话线索显示另一会话在跑同名批次/相邻主题 goal），你需要按一份设计文档或任务书实施其中一批改动，且用户要求或环境要求并行协同。

## Discriminator
两个文件面在写第一行代码前即可求交：设计文档已具名列出本批次的实施文件清单与批次边界，另一会话 goal 描述给出其文件/主题面（如一者动后端审批+Web 组件，另一者动桌面/浏览器回执）。交集为空→可并行；交集非空或不可判定→必须先协调或让位。这个判定不需要任何试探性改动。

## Short path
- 读完设计文档，抽取本批次具名实施文件清单与批次边界（如分批 M1/M2/M3），同时记录文档基线 SHA
- 查 Task Frontier/另一会话 goal 描述，抽取其在途任务的文件面或主题面
- 求交集：为空→登记独立 lane 并行开工；非空、同主题或不可判定→发协调请求或套用在途提交探测方法决定让位
- 核对当前 HEAD 与文档基线：基线落后时先按文档要求对最新代码复核其问题清单再动手
- 把 main 当移动目标：每次整合闸（merge/push）前用 merge-tree 复演当前 main 与本 lane 是否零冲突，闸前发时序协调请求
- 对方推进 main 后不重跑全流程：按 merge-tree 结果只增量重验受影响面，再走原定门禁（红→绿、独立审查、全量测试）

## Stop conditions
- 本批次修复红→绿全过、全量门禁真实 exit 0、已按闸流程合入并推送，且 worktree/lane 状态清理完毕
- 发现文件面交集非空，或对方合入了触及本 lane 文件的提交→暂停并行，先协调或重演冲突
- 对方在途提交与本批次内容等价（同主题同缺陷）→切到让位/独立验证路径，不再开平行流

## Verification
- merge-tree 复演输出零冲突才进 merge/push；有冲突先 rebase 或协调，不硬并
- 合并后跑全量门禁并核对真实回执 exit 0，不以抽样或跳过代替
- push 前后用远端 head 对账确认动作落地
- 收尾 git status 无未预期 tracked 变更；共享 main 上对方提交各自过闸的记录可追溯

## Counterexamples
- 另一会话与本批次同主题同缺陷（可能已有等价修复在途）→ 应套用『git log --all 探测在途提交』方法，命中等价则不开工；并行 lane 只会制造重复冲突
- 文件面交集为空但共享 conftest/锁文件/全局测试基建 → 逻辑冲突仍会撞，共享基建必须计入文件面再判定
- 设计文档只给行为描述、未具名实施文件 → 文件面需先从代码检索推导，不能假设 disjoint 直接并行
- 单会话独占仓库、main 不动 → 无需 lane 登记与协调闸，顺序开发更省
