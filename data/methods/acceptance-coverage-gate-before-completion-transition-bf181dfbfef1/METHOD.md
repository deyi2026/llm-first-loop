---
method_id: acceptance-coverage-gate-before-completion-transition-bf181dfbfef1
name: acceptance-coverage-gate-before-completion-transition
description: 状态完成类转移（task done / goal complete）不是证据汇总后的默认动作，而是 acceptance 的逐条闭合检查点。转移前把 acceptance 每一条（尤其『若X则Y，否则Z』式条件分支）映射到在手 evidence ref 或本会话观察；存在零观察的指涉物（URL/id/资源）即视为未闭合，先以已被记录命名的通道解析这一个未知量，再转移。本集 done 先行、随后才发现条件分支未验，被迫追加一条含 403 与 API 猜测失败的 6 次命令链回溯补验；若旧 URL 当时仍有残留，done 已成不诚实断言。与 fresh-read-authoritative-record 互补：那条管『对外部现状下终局断言前须重读权威源』，本条管『完成态转移前须先做 acceptance↔evidence 对账』。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:fb4a0414-5394-4ff0-af09-8f5511f928f7:91:1398505c48556a1eeeca
evidence_refs: learning:learn:bc055efe153e
created_at: 2026-10-11T02:29:06.417784+08:00
updated_at: 2026-10-11T02:29:06.417784+08:00
---
## Trigger
准备把任务/目标推进到完成态转移（task done、goal complete、close），且 acceptance 含条件分支（若X则Y，否则Z）或指涉本会话从未观察过的外部对象时。

## Discriminator
acceptance 文本与在手 evidence 同帧可比、对账零成本：回执回显的 acceptance 含一条条件分支，指涉一个本会话零观察的旧 URL；而全部在手证据（两条已 hydration 的命令回执、episode 记录）只覆盖新 URL 的在线状态。这个『条目→evidence 映射缺口』在转移当时即可机械检出，不需要任何新读取。

## Short path
- 转移前从任务记录读出 acceptance 全文，逐条与在手 evidence ref/本会话观察对账；每个缺口就是一个待解未知量，不应在转移后浮现
- 用已被会话内检索记录命名的通道解析缺口：experience 记录已声明该平台须走 CDP 直连，直接用它 nav 旧指涉物，跳过匿名请求必被反爬 403 的弯路
- 缺口解析（旧 URL 返回删除页→『否则删除』分支成立）后落一句判定依据，再 in_progress→done
- done 后核对回执回显的 acceptance 无未闭合项，才执行 goal 关闭

## Stop conditions
- acceptance 每一条均有 evidence ref 或本会话观察支撑 → 立即执行转移，不追加复核（复核即 post-sufficiency 浪费）
- 条件分支的取值已被在手证据确定 → 记录『该分支不适用/已满足』后直接转移
- 某条目需用户授权或会话外权威才能判定 → 中止转移，把缺口显式交回用户，不带缺口断言完成

## Verification
- 转移后回执回显的 acceptance 中不存在没有对应 evidence ref 或观察的条目
- 任何『转移后才补的验证』都记为一次 gate 失守信号并计数，用于后续 refine，不视为常规流程的一部分

## Counterexamples
- acceptance 为单一条款且已被已验 evidence 完全覆盖（如本集 001–009 类任务）→ 直接转移；此时设门只会制造无信息复核
- acceptance 指涉的仅是转移动作自身产生的内部状态（如『任务图中标记为 done』）→ 转移即证据，设门会造成无限回归
- 条件项需用户决策（如『经批准后删除』）→ 不可自验，转交用户而非替其判定
- acceptance 文本缺失或明显与目标无关 → 不得臆造隐藏条款来设门，只对显式条目对账
