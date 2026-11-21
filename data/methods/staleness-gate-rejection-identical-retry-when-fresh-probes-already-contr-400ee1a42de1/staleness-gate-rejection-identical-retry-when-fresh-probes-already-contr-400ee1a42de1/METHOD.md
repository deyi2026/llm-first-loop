---
method_id: staleness-gate-rejection-identical-retry-when-fresh-probes-already-contr-400ee1a42de1
name: staleness-gate-rejection-identical-retry-when-fresh-probes-already-contradict
description: 闸式调用（如 merge_review_start）被自描述确定性错误拒绝、reason 命名的是时效/滞后（base_or_head stale）而非工件结构或版本冲突时，先做零新调查的分类：若被拒前就已握有新鲜权威探针（ls-remote/repo HEAD）证明底层事实与刚 CAS 登记的精确 SHA 一致，且早前回执已观察到协调视图滞后真值、可机械解释该判定（甚至任务书已声明该滞后是预期状态），则拒绝只是宿主视图不同步的误报——原样重试一次就是最便宜的判别测试。不要立即开诊断战役：反复重验 git 事实、fetch、grep 宿主侧实现（往往不在可访问仓库内）、水合治理规则。重试同因再败才转入有界只读诊断。与『结构性拒绝是裁决、勿原样重发』互为反分支。
aliases: 审查闸报基线过期但刚才核对过一致, Host 视图没同步导致审查启动被拒, 被拒后先原样重试还是先排查, 合并审查一启动就报过期, gate 误报 stale 别急着重查 git
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:c58155a8-b020-4f34-aa57-2d5ac74f217a:0:0d1f0510185c3ad9bcde
evidence_refs: learning:learn:e677278827c6
created_at: 2026-11-17T16:39:07.655560+08:00
updated_at: 2026-11-17T16:39:07.655560+08:00
---
## Trigger
门禁/闸式调用被程序以自描述确定性错误拒绝，reason 命名时效性状态（如 lane_base_or_head_stale），且拒绝发生前本 run 已完成权威只读核对并刚以精确 SHA 成功登记/CAS（lane_update 成功）。

## Discriminator
三判据同时成立于被拒当时：(1) reason 命名『视图时效』而非工件结构（区别于 review_not_structured 类）或 CAS 版本冲突；(2) 已握新鲜权威探针显示 base/head 与登记值逐字一致（ls-remote main=lane.base，worktree HEAD=lane.head）；(3) 早前回执已观察到协调视图滞后真值（视图 main_head 落后权威 main，恰可机械产生 base_stale），且任务书已声明远程 head 滞后是预期状态——仓库侧不存在本方可修复项。三判据齐备 → 视图不同步，一次原样重试即判别测试。

## Short path
- 被拒后先做零新调查分类：读 reason 命名的是结构、版本、还是时效，不先跑任何命令
- 用已握回执核对三判据（权威探针=登记SHA；视图滞后已被观察到；本次登记 CAS 刚成功）
- 三判据成立 → 原样重试一次闸式调用（参数逐字节相同，可隔一个短同步拍）
- 重试成功 → 同 Run 等终态严格 JSON，核对 base/head/lane 与授权一致、P0=0/P1=0、Reviewer 只读，报告
- 重试同因再败 → 才进入有界诊断：一次 merge-base 探针 + 一次视图-vs-仓库比对；不搜索不在可访问仓库内的宿主侧实现

## Stop conditions
- 取得终态 JSON 回执且 base_sha/head_sha/lane_id 与授权精确 SHA 逐字一致 → 停止，报告
- 第二次同 reason 拒绝 → 停止重试，转入有界诊断或按任务书 HOLD 并列 P0/P1
- 分类发现 reason 命名工件结构或 CAS 版本冲突 → 改走对应既有方法（修工件 / 重读后单次 CAS 重试），不套用本条

## Verification
- 重试调用与首次被拒调用参数逐字节相同（未夹带任何『修正』），证明判别的是视图同步而非参数
- 终态回执为严格 JSON，verdict/gate 与任务书一致，p0=0/p1=0
- 回执 base_sha/head_sha/lane_id 与授权 SHA 逐字相等
- Reviewer 轨迹只读（read/search 类，零 shell/零写），child_id 真实记录

## Counterexamples
- reason 命名产物结构形态（如审查记录不是顶层纯 JSON）：这是裁决不是延迟，原样重发必然复败，须先修工件再重发（既有 structural-rejection-is-verdict 方法覆盖）
- CAS 版本冲突且错误点名 expected/current 值：须先只读重读、核对前置条件后做单次 CAS 重试（既有 version-conflict-reread 方法覆盖），不属于本条
- 未握有新鲜权威探针、或探针显示 base 确实落后真 main（分支真的需要 rebase/merge）：滞后判定为真，重试只是烧一次调用，应先做仓库侧核实
- 视图滞后此前未被任何回执观察到、且无法机械解释该判定：先花一次廉价权威探针核实真值，再决定重试还是诊断，不盲重试
