---
method_id: disjointness-precheck-gate-first-side-archaeology-in-wait-window-91157afd98e7
name: disjointness-precheck-gate-first-side-archaeology-in-wait-window
description: 主任务需异步审查闸放行（如 git push）、交接又附带一个疑似无关且已开出修复处方的环境/门禁问题时：先用一条按侧线路径过滤的批次范围 diff 证明不相交，随即启动长杆异步闸，把侧线只读考古放进等待窗并行完成。受影响清单以门禁自身枚举为准（交接常只报其一）；处方脚本若写入审批/基线痕迹、自身契约区分『基线重建 vs 人工审阅』且交接注明『人工跑』，则不代跑、不混入已冻结批次，向用户呈现执行主体选项。
aliases: 等审查结果的时候先查别的还是干等, 交接里让人工重跑的审批脚本能不能替跑, 推送前先启动审查还是先查环境问题, 审查等待窗口能塞什么活, 基线对不上要不要顺手重新生成manifest, 侧边问题会不会污染这次推送批次
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:9fd8f866-77d0-4951-8e25-686ea3761026:32:35504a95f58c9bcf745b
evidence_refs: learning:learn:b94669232b97
created_at: 2026-11-09T15:29:09.209231+08:00
updated_at: 2026-11-09T15:29:09.209231+08:00
---
## Trigger
交接同时包含：需异步审查闸放行的主行动（push/发布/全量测试）+ 一个疑似无关、且用户已给出修复处方（如『人工跑 X 重新审批』）的环境或完整性门禁问题

## Discriminator
两条启动闸前即可廉价取得的事实：①批次范围 diff 按侧线路径过滤为空（git diff --name-only <remote-tip>..HEAD -- <侧线路径>）⇒ 侧线与待推内容可证明不相交，且侧线调查可全程只读、不会漂移 scope=tree 的审查指纹，因此无需先做完侧线根因考古再启闸；②处方脚本文档自述 actor/诚实契约（baseline ≠ 人工逐字审阅，代跑须如实标注身份）且交接写明『人工跑』⇒ 代跑会伪造审批痕迹或需要用户未曾给出的身份标注。

## Short path
- 一次取齐主行动最小前置事实：ls-remote 直读远端真值 tip、ahead 数、快进/祖先关系、受跟踪树干净
- git diff --name-only <remote-tip>..HEAD -- <侧线路径> 判定侧线与批次不相交（一条命令，不做全量考古）
- 不相交 ⇒ 立即启动长杆异步审查闸（review_admission start），不要先做完侧线根因考古
- 等待窗内只读完成侧线考古：以门禁自身枚举为准确定受影响清单（交接常只报其一，实测两个技能都被隐藏）、逐项哈希对照 manifest、用基线时间戳 vs 变更历史定位『陈旧基线遗留而非本批引入』
- 侧线处方若写审批痕迹：读脚本自身诚实契约；报告者指定人工或契约要求身份标注时不执行，向用户呈现两路选项（本人跑 / 授权带标识代跑），修复归独立批次另过闸
- status=PASS 后进入零写窗口，仅以裸命令执行被准入动作，并在目标面（ls-remote==本地 HEAD）对账收口

## Stop conditions
- 过滤 diff 非空（侧线文件出现在批次范围内）⇒ 先裁决并入批次或显式延期披露，再启闸
- 侧线调查需要任何写操作 ⇒ 不放入等待窗（指纹漂移会使 PASS 失效）
- 侧线直接阻断主行动（被门禁隐藏的技能正是执行闸或主任务所需）⇒ 先修侧线并向用户升级
- 取得 PASS 资格 ⇒ 冻结一切写入，只执行被准入的单一动作

## Verification
- start 回执中的 push_src_commit / push_remote_commit 与第一步直读事实一致
- 整个等待窗内 git status 受跟踪面保持干净（审查指纹零漂移）
- 完成后 ls-remote 与本地 HEAD 一致、ahead/behind 归零
- 确认未运行任何写入审批/基线痕迹的处方脚本；侧线修复另起独立批次并单独过闸

## Counterexamples
- 侧线文件真的出现在批次 diff 中（如本次推送确实包含 skills/ 变更）→ 必须先处置侧线再启闸，先启闸反而白烧一次长杆审查
- 审查闸是同步快速放行、无异步等待窗 → 排序无墙钟收益，按主任务顺序串行即可
- 处方脚本是 provenance 中性的机械修复（如 lint --fix、重建无 actor 语义的缓存）且用户已授权代跑 → 直接在独立批次执行，无需升级询问执行主体
- 侧线正是主行动的前置依赖（被隐藏的技能就是闸本身需要的）→ 侧线优先，不能并行
