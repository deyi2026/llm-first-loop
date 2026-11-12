---
method_id: gate-param-inapplicable-swap-widening-keep-gated-command-verbatim-f9f989d6029e
name: gate-param-inapplicable-swap-widening-keep-gated-command-verbatim
description: 带 kind 条件合同的准入闸（review_admission 类）确定性拒绝用户指令逐字规定的参数组合（如 git_push 不接受 scope=patch）时，拒绝 reason 即合同差分：先读 schema 核对枚举与覆盖语义，把被点名维度换成覆盖严格更宽的合法值（tree ⊇ patch+paths），被闸命令/workdir/kind 逐字不动，单次重发。安全边界：只允许放宽审查覆盖，绝不收窄、绝不改被闸动作，并在最终报告披露与指令字面的偏差。缺字段类拒绝走补字段路径，权限类拒绝走授权流程，均不适用本卡。
aliases: push审查scope被拒换整树, 审查闸参数对kind不适用, 用户给的闸参数和闸合同冲突, git_push 审查范围只能整树, 准入被拒参数不适用怎么重发
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bc99ff08-658c-4355-afd2-b4b2ecc29011:139:342a6b69b8c2cf3d842f
evidence_refs: learning:learn:e6c789f44ac9
created_at: 2026-11-12T13:59:22.703230+08:00
updated_at: 2026-11-12T13:59:22.703230+08:00
---
## Trigger
准入/审查闸 start 调用被确定性拒绝（accepted:false），reason 命名『某参数对当前 kind 不适用』（如 scope=patch 对 git_push），且该参数取值来自用户指令的逐字规定，与闸自身合同冲突

## Discriminator
拒绝码指向 kind 条件化适用性，而非缺字段或权限不足；同时任务书自身的验收措辞（如『审查完整拟推送 commit set 及交叉上下文』）已要求超出 paths 清单的覆盖面，而 schema 中存在覆盖严格更宽的合法枚举值（tree ⊇ patch+paths）；被闸动作（command/workdir/kind）未被点名违规，可原样保留

## Short path
- 拒绝后不重试原参数、不凭空猜值：get_tool_schema 核对该参数枚举与各值覆盖语义，把 reason 机械翻译成『唯一需改维度=scope，合法替代值=tree』
- 校验放宽方向：替代值覆盖 ⊇ 原请求（tree 包含全部 7 路径），且满足任务书『完整 commit set 及交叉上下文』的验收措辞；command/workdir/kind 保持逐字不变
- 单次重发 start；受理后核对回执 push_src_commit/push_remote_commit 与实测 HEAD/远端逐位一致
- 按回执 waiting_protocol 有界轮询（repeat_guard 触发时先落账本再有界等待），终态须 qualification=PASS 且 candidate_sha256 与受理回执一致
- 被闸动作逐字执行；push 后 ls-remote 逐位核验远端=候选 HEAD
- 最终报告如实披露与用户指令字面参数的偏差（scope patch→tree）及放宽理由

## Stop conditions
- reason 指向被闸命令/动作本身不合规 → 停止上报，绝不通过改命令绕闸
- 唯一合法替代值会缩小而非扩大审查覆盖（如被迫 tree→patch）→ 不自动重发，先与用户确认
- reason 属缺字段或权限/资格不足类 → 换枚举值无效，分别走补字段重发或授权链路
- 重发受理回执的 src/remote commit 与实测漂移 → 停止，回到只读预检

## Verification
- 重发受理回执 scope.effective=tree 且 push_src/push_remote commit 逐位匹配实测 HEAD 与 ls-remote
- 终态 PASS 回执的 candidate_sha256 与 start 回执一致（同一冻结材料，未换目标）
- push 后 git ls-remote --heads origin main 逐位=候选 HEAD；候选 worktree 与主工作区均未被改动
- 报告包含参数偏差披露：用户原指令 scope=patch → 实际按合同使用 tree

## Counterexamples
- 用户明令只审指定 paths（成本/保密考虑）且禁止整树审查 → 放宽到 tree 违背意图，应停下询问而非自动重发
- kind=full_test 等本身接受 patch+paths 的闸 → 无此约束，按义务推导 scope 即可，勿默认 tree
- reason 为权限/资格类拒绝 → 换 scope 无效，需走授权流程
- 被拒的是 command 本身（如禁止的 refspec 或 --force）→ 唯一合规动作是停止上报，任何参数调整都等于变更被授权动作
