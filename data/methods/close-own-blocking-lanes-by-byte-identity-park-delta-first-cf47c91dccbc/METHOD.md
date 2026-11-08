---
method_id: close-own-blocking-lanes-by-byte-identity-park-delta-first-cf47c91dccbc
name: close-own-blocking-lanes-by-byte-identity-park-delta-first
description: 本会话被跨会话请求或用户要求把名下非终态 lane（正卡他人 main 写门/合并闸）收敛为终态时，不把请求方转述的事实（『分支 0 提交』『目标物已在 main』）当作收口证据：先以共享 lane 账本+git 为真值，对每条 lane 做一次字节级身份比对——worktree 在途文件（untracked 或 M）的 sha256 vs 当前 main HEAD 树同路径 `git show HEAD:path | sha256sum`。逐字节相同=空转，直接 closed 收口（理由记比对哈希）；存在独有未提交改动且当前边界禁止 commit/merge/push（内容无复审 PASS）→先把 delta 停泊为带 sha256 的补丁工件再 closed（非 abandoned），理由记停泊路径与哈希；仅当确能在边界内推进才给 ETA。收口后 help_resolve 并一次性核对账本/事件/队列。
aliases: 被别的会话催着收自己的 lane 怎么办, 关 lane 前怎么不丢 worktree 里的活, lane 到底算不算白干怎么查, 卡住别人合并的 lane 怎么放行, 先把改动存成 diff 再关分支通道, 用自己的文件哈希对 main 判断重复
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:0a79bf7c-4ae8-4f1a-be35-75280ea0a40e:600:2464afe72a76c1980ecc
evidence_refs: learning:learn:8a4bb980d586
created_at: 2026-11-08T10:04:10.035780+08:00
updated_at: 2026-11-08T10:04:10.035780+08:00
---
## Trigger
跨会话唤醒/协调请求（或用户指令）要求本会话把名下仍处非终态（active/open）的 lane 给出明确终态，典型原因是 lane 状态卡住他人的 main 写门；请求通常附带建议处置（空转则 close、要做给 ETA）与硬边界（不动他人 lane、不 push、不改产品代码）

## Discriminator
每条 lane 的终态选择由一个本地可算的字节级事实唯一决定：该 lane worktree 内在途目标文件的内容 sha256 是否等于当前 main HEAD 树同路径文件。相等=空转可径直 close；不等=存在独有工作，close 前必须先停泊。注意账本里 head==base 只说明分支无提交，区分不了『内容已进 main』与『内容独有』，必须比内容本身；请求方的转述只是线索不是证据

## Short path
- help_inbox 以正确 scope 取阻塞请求原文：点名 lane、期望动作、边界清单
- grep 共享 lane 账本取每条被点名 lane 的 branch/base/head/worktree/status 真值，不信转述
- 单次探针完成裁决：main head、各 worktree porcelain 状态、在途文件 sha256 与 git show HEAD:path 的 sha256 比对
- 裁决分支：字节相同→lane_close(空转收口，理由含哈希比对)；独有未提交改动且不可 commit（无复审 PASS/边界禁 push）→先导出停泊补丁（diff 与全文 sha256 落盘）再 lane_close(非 abandoned，理由含停泊路径与哈希)
- help_resolve 请求；一次性核对 lanes 账本终态记录、closed 事件、队列不再含本会话 lane，然后停止

## Stop conditions
- 每条被点名 lane 在账本最后记录均为 closed 且有对应 closed 事件可查
- 阻塞请求已 resolved，回执含理由与停泊工件哈希
- lane 队列/main 写门不再被本会话名下 lane 阻塞
- 边界全程未破：未 push、未提交未过闸内容、未动他人 lane

## Verification
- 重算停泊补丁与全文 sha256，与 close reason 中登记值一致
- lanes 账本每条 lane 最后一条 status=closed，事件流有对应 lane.closed 记录
- help_resolve 回执 state=resolved
- git show HEAD:同路径 | sha256sum 与空转判定值可复现

## Counterexamples
- lane 分支 head≠base 且含 main 没有的提交：不是空转，需走 rebase/合并或给 ETA，不能直接 close
- 在途差异是业务上已废弃的格式化噪声：可 abandoned 收口并注明，无需停泊补丁
- 边界允许 commit 且复审通道可用：直接走正常提交+队列，停泊反而制造双重真值
- lane owner 是其他会话：不能代为收口，应转 owner 协调/死信上报路径
