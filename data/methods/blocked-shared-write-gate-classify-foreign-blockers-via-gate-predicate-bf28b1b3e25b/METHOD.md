---
method_id: blocked-shared-write-gate-classify-foreign-blockers-via-gate-predicate-bf28b1b3e25b
name: blocked-shared-write-gate-classify-foreign-blockers-via-gate-predicate
description: 共享写闸（如 main 的 commit/push 守卫）以"存在他人 active 条目"拒绝你的操作时，不要枚举队列历史快照、也不要换措辞重试：把三个判据事实一次取齐——①闸源码声明的输入账本与谓词（按谓词过滤账本，得到精确阻塞集）；②闸有无 TTL/失效回收/override（决定"等待"是策略还是结构性无限期冻结）；③每条阻塞项的属主活跃度×head 是否真实未合并（活/休眠×真工作/残留）。由此分流：活着→等待或最小强制值提醒；休眠+真工作→提醒属主收口+提交演进建议；残留→提议清理；无 escape-hatch→上报用户三选（等/人工授权代收口/演进），绝不静默接管他人 lane 或绕闸。
aliases: push 被别人 lane 卡住怎么排查, 休眠会话冻住 main 推送, 写闸没有 TTL 该等还是升级, 阻塞 lane 是残留还是真没合, 他人 active lane 挡住共享写操作
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:5912:76fd959e766aa44c49d7
evidence_refs: learning:learn:6d50a9f1f660
created_at: 2026-11-09T10:54:09.556223+08:00
updated_at: 2026-11-09T10:54:09.556223+08:00
---
## Trigger
需要向共享主干/共享资源执行写操作（push/commit 到 main 等）被治理闸以"他人 active lane/锁/租约存在"为由拒绝，或续跑任务中已知此类阻塞需收口判定"等还是升级"时。

## Discriminator
闸的实现源码就是合同：它写明权威输入账本与判定谓词（按 id 取最后快照、status 属 active 集、owner 非本会话），而队列状态工具只是含大量终态历史的 UI 镜像；同时闸源码中 TTL/回收/override 分支的有无，在动手前就决定等待是否可行。首次检索即命中 guard 实现与其测试文件路径，无需猜测模块路径或枚举全部 37 条队列条目。

## Short path
- 绑定现状：git status/log + goal 回执，确认已闭项（main head、审查回执、验收口径是否包含被阻塞动作）与未闭项（远端同步）。
- 一次检索定位并直读闸源码全文：回答输入账本是哪个文件、判定谓词是什么、有无 TTL/回收/override 三个未知量。
- 按闸自己的谓词直读账本（如 jq 过滤 active 状态且 owner≠我），得到精确阻塞集（本例仅 2 条），不枚举队列历史。
- 对每条阻塞项做 2×2 分类：协调事件流看属主最后活跃时间（活/休眠）× git diff main...head 看是否真实未合并（真工作/残留）。
- 按分类选最小越界动作：活→等待；休眠+真工作→分级消息提醒属主收口（发前先读该字段被哪个闸消费、作用半径，选最小强制值）；无 override 且持续受损→提交演进建议（心跳/TTL/分判据）。
- 向用户披露三态（等待/一句话授权代收口/演进），越界选项留给用户决定，停止。

## Stop conditions
- 按谓词过滤账本后阻塞集为空 → 直接执行原写操作，无需分类与协商。
- 每条阻塞项完成"活/休眠×真工作/残留"分类、且闸 escape-hatch 有无已确认 → 诊断结束，只做通知/演进/披露，不再重读闸与账本。
- 用户已选定等待或授权某条收口路径 → 不再自行尝试其他解法或探测绕闸口子。

## Verification
- 用闸源码谓词重放账本原始数据（jq 过滤），阻塞集与闸拒绝事实一致。
- 休眠判定以协调事件流该属主最后时间戳为准；"非残留"以 diff main...head 非空为准。
- 最终报告逐项可核：已闭项给 head/回执，未闭项给 lane/owner/分类证据，越界动作显式列为"未做"。

## Counterexamples
- 闸带 TTL/租约过期或重试可过（回执显示瞬态竞争）→ 等待/重试即可，不需要属主分类与演进提案。
- 阻塞条目 head 已完全并入 main（diff 为空）→ 是残留而非真工作，正解是提议清理/关闭，不是提醒属主"合完再关"。
- 阻塞条目属主是本会话自己（自持锁）→ 先收自己的 lane，不存在跨会话协商。
- 队列快照工具本身就是闸的权威输入而非 UI 镜像 → 直读它即正确；方法要点是"以闸声明的输入为准"，不是"永远别读队列"。
