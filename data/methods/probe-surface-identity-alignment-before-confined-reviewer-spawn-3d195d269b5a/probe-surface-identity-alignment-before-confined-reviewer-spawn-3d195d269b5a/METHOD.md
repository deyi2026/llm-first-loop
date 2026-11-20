---
method_id: probe-surface-identity-alignment-before-confined-reviewer-spawn-3d195d269b5a
name: probe-surface-identity-alignment-before-confined-reviewer-spawn
description: 受审对象被钉死在不可变身份（精确 commit SHA/tree、版本号、record id）上，而被委派的 reviewer 只配了路径寻址工具（read_file/search_files），只能看见可变默认面（当前工作树/活库当前态）时：把『观察面是否等于冻结身份』当作 spawn 前的第一未知量，先用一次廉价身份探针解决（rev-parse HEAD 对比 brief SHA + ls-tree 确认目标路径在该树中）；不对齐就先补齐对齐（只读 worktree 检出、git show 导出+对象哈希校验）或向用户请求改面，再 spawn。否则 reviewer 会把全部预算花在发现错位上，产出 fail-closed『对象缺失』BLOCK，父侧还要在同面重复 null、最后靠 git 才定位到真根因（checkout 分叉），审查零行开展。
aliases: reviewer 说文件不存在, 审的还是冻结 SHA 吗, checkout 和审查对象对不上, 只读子代理看不到文件, 工作区不在候选提交上, 审前先核对 HEAD
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:520bb4af-a364-4194-87f6-f98bae40353c:36:1cf94042f81ff646e07f
evidence_refs: learning:learn:0516d462ccf9
created_at: 2026-11-17T18:17:46.322392+08:00
updated_at: 2026-11-17T18:17:46.322392+08:00
---
## Trigger
即将 spawn 一个被限定为路径/表面寻址只读工具（read_file/search_files，无 shell/git/网络）的独立 reviewer，而任务书把受审对象钉在精确不可变身份（SHA/tree/版本）上，且当前观察面（工作树 checkout / 活库状态）与该身份的一致性尚未核验。

## Discriminator
spawn 时两个已可见事实的组合即暴露错位风险：任务书以 commit 身份寻址（冻结 HEAD、tree id、唯一新增路径），而工具白名单只按文件系统路径寻址当前 checkout；两者的等价性从未被验证（任务书未声明 checkout 就在该 SHA 上）。任何一次 HEAD/ls-tree 探针都能在花掉子代理预算之前，把『对象不可达』与『内容缺陷』这两类失败分开。

## Short path
- 从任务书解析对象身份（SHA/tree + 唯一受审路径）与观察者寻址方式（工具白名单），列出未验前提：surface==identity？
- 未知量1：工作树是否即冻结身份？一次 git rev-parse HEAD（必要时 git ls-tree <sha>:<dir> 查目标路径是否存在）与 brief 比对。
- 一致 → 按原任务书 spawn，reviewer 直接读目标文件做实质审查。
- 分叉（本集：HEAD 为另一提交且非候选后代）→ 先补对齐：只读 git worktree add 检出该 SHA、或 git show <sha>:<path> 导出+对象哈希校验后把 reviewer 指向对齐面；或请用户切 checkout。
- spawn 后子代理预算全部落在受审内容上；收到绑定精确 SHA+行号的终态裁决即转述并停止。

## Stop conditions
- spawn 前身份探针已确认 surface==冻结 SHA/tree，或错位已通过 worktree/导出补齐并经哈希核验
- reviewer 已给出绑定精确 SHA 与行号的终态裁决（PASS/REVISE/BLOCK），不再追加任何发现性动作

## Verification
- 探针回执落账：HEAD 哈希==brief 冻结 SHA（tree id 一致）
- 若走导出路线：导出产物的 git 对象/blob 哈希与 ls-tree 记录一致后才交给 reviewer
- 终局裁决文中的 SHA 与任务书冻结 SHA 逐字一致；账本中把 reachability 类失败与 content 类失败分型记录

## Counterexamples
- reviewer 自带身份寻址能力（可直接 git show <sha>:path，或任务书给的路径位于已对齐的专用 worktree/导出目录内）→ 不存在对齐未知量，探针冗余，直接 spawn
- 受审对象本就不是版本钉死的（审当前工作树现状、live store 当前态）→ 表面即身份，无对齐问题
- 用户明确要求审当前 checkout 而非某 SHA → 面与身份的分歧是任务本意，不适用
- reviewer 已耗尽预算返回『文件不存在』后才介入 → 不适用预探针规则本身，此时不要在同面重复 null，直接上身份层探针（ls-tree@SHA、rev-parse）定位错位
