---
method_id: receipt-anchored-params-before-mutating-calls-0b9f400a174c
name: receipt-anchored-params-before-mutating-calls
description: 对会改变系统状态的控制调用（重启/发布/部署），参数不凭记忆或习惯默认值拼装：target 枚举、generation/id 等逐字取自同一控制平面最近的回执/快照；workdir 等环境参数若无任何已观察事实锚定，先用 pwd 级廉价探测或直接用 cwd，不提交猜值。变更前先落回滚锚点；受理回执中的异步语义（action_id、两阶段等待）用于安排延后验证而非同步阻塞。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:1113:aa52c5325df9b506b438
evidence_refs: learning:learn:c627dcd51688
created_at: 2026-09-23T15:37:58.811283+00:00
updated_at: 2026-09-23T15:37:58.811283+00:00
---
## Trigger
即将调用 state-changing 控制类工具（restart/publish/deploy/删除类），其参数含枚举域或版本号；或调用需要 workdir/绝对路径，而此前没有任何观察事实锚定该值

## Discriminator
检查最近一次同平面回执/快照是否已枚举所需参数域——本集 runtime snapshot 已列出服务 target（web/feishu/learning）与 desired generation 85，restart 参数本可逐字照抄；环境参数则看 pwd/cwd 是否已被观察。有出处→照抄；无出处→先只读探测，绝不把假定的 /workspace 之类默认值直接提交

## Short path
- 用已持有的 runtime/desired 回执确定 live head 与 desired head，diff 后把改动分类为'静态直读产物（免重启）'与'进程加载代码（需重启）'，直接回答重启必要性
- 先落回滚锚点：对 live/desired 两个 head 打 tag，确认工作树干净，记录不在版本库的构建产物（如 dist）及其重建路径
- 提交变更调用前逐参数对表：target 用回执枚举值、generation 用回执数字，逐字照抄，不拼自定义格式（避免 target 参数错误重试）
- 读受理回执提取异步语义（action_id、两阶段等待/不占锁），据此安排延后续跑做终态验证，而不是同步阻塞轮询
- 验证新 pid、head 对齐 desired、无 admission barrier 后收口；失败只报告并给回滚建议，是否回滚由用户决定

## Stop conditions
- 所需参数在最近回执或工具 schema 中都能指认逐字出处，且与用户意图一致 → 立即提交，不再额外探测
- 回执显示的 desired 与预期不符（generation/head 不对或有 admission barrier）→ 停止提交，先向用户确认
- 已取得受理回执并安排了验证续跑 → 停止继续查询或枚举其他来源

## Verification
- 提交前自检：变更类调用的每个参数值都能在最近回执中指认出处
- 提交后用 status(action_id) 确认终态 succeeded、head 对齐 desired、无 admission barrier
- 回滚锚点存在且两端都指向不可变提交（tag 已打、工作树干净、未入库工件已记录）

## Counterexamples
- 只读幂等、失败即返回参数域提示的廉价调用（search/ls/读文件）：直接试错更短，预先探测反而增加调用数
- 工具 schema/描述已内嵌参数枚举与默认值：直接按 schema 取值，无需先查回执
- 回执可能过期（控制面状态已被其他会话变更）：照抄旧 generation 会提交错目标，须先刷新 status 再取参数
- 纯本地 git 操作（tag/checkout）的参数来自刚验证过的 git log 输出，不需要额外 provenance 探测
