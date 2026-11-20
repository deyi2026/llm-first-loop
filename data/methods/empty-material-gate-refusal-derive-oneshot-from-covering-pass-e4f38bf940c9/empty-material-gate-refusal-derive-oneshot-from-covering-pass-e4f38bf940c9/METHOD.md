---
method_id: empty-material-gate-refusal-derive-oneshot-from-covering-pass-e4f38bf940c9
name: empty-material-gate-refusal-derive-oneshot-from-covering-pass
description: 材料型准入闸的资格材料定义为『相对审查基点的差异』。当在场事实已显示基点==HEAD（push_src 与 push_remote 相等、远端已核验、工作树未被本 run 改动）时，该类请求注定被确定性拒绝（无材料可审），不应提交。正确路径是闸自身文档化的例外条款：同一父级、覆盖当前 HEAD 树的 git_push PASS 在档时，按『树逐字节相等』派生一次性复跑资格。已被拒时，拒绝文本引用的例外条款即权威配方——等在途覆盖 PASS 到手后按条款派生，绝不重发注定被拒的请求，也绝不为凑材料伪造差异或硬闯豁免。
aliases: 没差异可审被拒怎么办, 全推送了树干净还能拿本地复跑授权吗, 用push审查通过派生一次性复跑资格, full_test空材料拒绝, 审查门说没有可审的东西
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d901b48e-25bf-45f0-a33f-23eaa879ddc3:809:1b33c38e8ba981b2f7a0
evidence_refs: learning:learn:df38f2b69e0d
created_at: 2026-11-19T18:59:05.208895+08:00
updated_at: 2026-11-19T18:59:05.208895+08:00
---
## Trigger
向材料型准入闸（材料=待审差异/待审内容）发起资格请求前，在场事实已表明材料必为空；或已收到『无材料/空壳拒绝』类状态性 reason（非缺字段、非权限类拒绝）。

## Discriminator
发起请求前已在场：同批 git_push acceptance 回执里 push_src_commit==push_remote_commit（或已核验远端==本地 HEAD、树未被本 run 改动）→ 差异材料必空，full_test 类请求注定被拒；拒绝文本自身引用的例外条款（覆盖当前 HEAD 树的 git_push PASS 可派生一次性复跑资格）指明唯一合法替代路径。

## Short path
- 提交资格请求前，先用在场事实核对材料前提：基点/远端是否==HEAD，工作树与未跟踪区是否真有差异
- 前提为空时不要提交该请求；改走例外路径——确认覆盖当前 HEAD 树的 git_push 审查已在途或已 PASS，等待其终态
- 若请求已被拒：把拒绝文本中的例外条款逐字当配方执行，不重发原请求、不制造材料
- 覆盖 PASS 到手后按条款派生一次性资格，并核对派生回执字段
- 用派生资格消费被闸动作，到此停止路由，不再触碰原请求通道

## Stop conditions
- 派生回执 granted 且 basis 显示树逐字节相等（push_pass_tree_identical）→ 停止路由，直接进入消费
- 拒绝 reason 属缺字段或权限/授权类 → 本卡不适用，转补字段差分或授权流程
- 无覆盖当前树的 PASS、或 PASS 之后树已漂移 → 派生前提不成立，停下改走真实差异提交或重新审查，不得硬派生

## Verification
- 派生回执字段核对：derived=true、one_shot=true、derived_from=在档 PASS 的 child_id、basis 含当前 head_tree 摘要
- 派生 target 的 worktree 与覆盖 PASS 所审树一致，消费前树哈希未变

## Counterexamples
- 存在未推送提交、脏工作树或未跟踪文件（材料非空）→ 正常提交 full_test，派生路径无关
- 拒绝原因是权限/授权不足而非无材料 → 派生无效，必须走授权流程
- 覆盖 PASS 的树与当前 HEAD 不一致（有漂移或 scope 收窄）→ 派生会被树复检挡下，应先折入漂移重审
- 闸没有任何书面例外条款 → 不得即兴派生，向用户报告并等待裁决
