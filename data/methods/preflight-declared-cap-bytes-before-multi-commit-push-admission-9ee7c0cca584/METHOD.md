---
method_id: preflight-declared-cap-bytes-before-multi-commit-push-admission-9ee7c0cca584
name: preflight-declared-cap-bytes-before-multi-commit-push-admission
description: 多提交推送需过带字节上限的审查准入门时，若上限已在本会话已读信息中自声明（如待推 HEAD 提交信息自声明具体上限；**2026-10-28 复核**：现行上限为 2.5M 字符，192KB 已废止，本方法只在材料逼近当前上限或门自声明时才启动），首次准入前先用一条本地命令量化门将冻结的 delta 字节数并比对；超限则不烧注定失败的准入轮，直接按累计字节找拆分边界（前缀与剩余增量均低于上限），在边界提交开临时 worktree 分段准入、各段独立 PASS 后逐字单条 push 并逐段 ls-remote 核验。把『准入被拒→读门组装代码→重拆』的整轮恢复压缩为前置预检；预检前须确认门的材料口径是 committed delta 字节而非全文件尺寸。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:1384:3a16bb18ed4f136200af
evidence_refs: learning:learn:6dc07e0f465d
created_at: 2026-10-21T20:06:33.802743+08:00
updated_at: 2026-10-21T20:06:33.802743+08:00
---
## Trigger
把领先多提交的本地分支推送到带审查材料字节上限的准入门主仓之前，且该上限值已出现在已读信息中（待推提交信息、门文档、历史拒绝回执）。

## Discriminator
待推 HEAD 自己的提交信息已自声明门的上限与计费口径（如『…触发审查材料192KB上限…使 push delta 可审』），且待审范围是多提交累积 delta——上限与口径都已在手，只差一条本地量化命令即可确定首次准入必拒。

## Short path
- 钉权威远端：remote -v 看身份线确认主仓（不按默认名），确认本地干净、ahead N、零分叉
- 读待推提交的自描述信息，提取已声明的上限值与材料口径（delta 字节 vs 全文件）
- 本地量化 push_base..HEAD 的 delta 字节数（一条 diff 命令统计），与上限比较
- ≤上限 → 单次准入推送即结束；超限 → 逐提交累计字节找拆分边界：前缀累计 < 上限且剩余增量 < 上限
- 在边界提交开临时 worktree（HEAD 停在拆分点，不改任何提交内容），对前缀段发起准入；PASS 后逐字单条 push（不与验证命令 && 合并），ls-remote 核验到位
- 对剩余段在主 checkout 发起准入（push base 应解析到新远程 ref），PASS 后同样单条 push；终态双向 rev-list 零差距后清理 worktree

## Stop conditions
- ls-remote 权威远端 ref 等于目标提交，且双向 rev-list 计数均为 0
- 预检结果 ≤ 上限：单批准入推送即完成任务，不进入拆分

## Verification
- 每段准入回执的 push_remote_commit 等于该段真实远程起点（分段覆盖不重不漏、无绕审）
- 每段 push 后用独立命令 ls-remote 核验远程 ref 到位
- 终态：远端 ref == 本地目标提交且双向零差距；全程未改任何提交内容

## Counterexamples
- 上限未在任何可见信息中声明且无历史拒绝回执：无从预检，应先正常准入、被拒后按容量拒绝字符串读门自身组装代码再拆分（恢复路径，另一张卡）
- 单提交或 delta 远小于上限：预检是多余开销，直接准入
- 超限主因是可再生运行期工件刷新（时间戳等）：应还原到远端已推版本使净变化归零、排除出材料，而非拆分推送
- 门按完整文件内容而非 diff 计材料（如树干净类门）：预检口径必须是全文件尺寸，delta 字节数不适用
