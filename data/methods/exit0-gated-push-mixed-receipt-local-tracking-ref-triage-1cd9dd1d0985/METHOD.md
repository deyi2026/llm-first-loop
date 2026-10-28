---
method_id: exit0-gated-push-mixed-receipt-local-tracking-ref-triage-1cd9dd1d0985
name: exit0-gated-push-mixed-receipt-local-tracking-ref-triage
description: 准入闸内一次性授权 git push 回执为 exit 0 且含远程受理行，但 stderr 同时带本地 refs/remotes 追踪 ref 写入错误、且治理横幅声称『审查资格未核验』。按错误作用域解剖回执：refs/remotes/* 且指向父仓 .git 的错误是本地记账失败，不影响远端；横幅自身文本已声明以工具回执为准。剩余唯一未知量（远端真实 SHA）用单次只读 ls-remote 比对解决；绝不因本地错误行或横幅而重试一次性命令或重跑审查。与 failed-oneshot triage（exit≠0）互补，方向相反。
aliases: git push exit 0 但 error update_ref failed, 成功 push 后 unable to create directory refs/remotes, 本地 tracking ref 更新失败不等于 push 失败, sandbox 不能写 .git refs/remotes 报错, 闸口横幅说审查资格未核验能否忽略, push 成功后 ls-remote 远端核实
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32aa0d7a-4f07-4a1c-8d9a-5083cb2761d4:1:46f96459b291b9ac940d
evidence_refs: learning:learn:1bea47cb911b
created_at: 2026-10-27T13:39:21.024389+08:00
updated_at: 2026-10-27T13:39:21.024389+08:00
---
## Trigger
唯一被审查准入授权的一次性强保护命令（gated git push 等）已执行，回执 exit code=0 且含 `<old>..<new> HEAD -> <分支>` 远程受理行，但 stderr 同时出现 `error: update_ref failed for ref 'refs/remotes/...'` 类本地写入错误，和/或闸口横幅宣称审查资格未核验

## Discriminator
同一回执内三个同时可见的信号：①退出码 0；②`old..new HEAD -> 目标分支` 只在远端受理后打印；③错误行 ref 命名空间是 refs/remotes/<remote>/… 且路径落在父仓 .git（在沙箱写允许面之外），而非远端 refs/heads 目标；横幅自身文本声明『本行不是凭据，实际执行状态以本工具回执为准』

## Short path
- 逐字、单条执行被准入的唯一 push 命令（沿用 admission-gated verbatim 纪律，不与验证命令合并）
- 对回执按行分类定权威：exit 0 + `old..new HEAD -> 目标分支`=远端已受理；`error: ... ref 'refs/remotes/...'`+父仓 .git 路径=仅本地记账失败；闸口横幅自身已免责声明非凭据，以工具回执为准
- 此时只剩一个未知量：远端是否落在授权 SHA → 用单次只读 `git ls-remote <remote> refs/heads/<分支>` 与授权目标 SHA 逐位比对
- 比对一致 → 立即收尾报告真实收据（如实标注本地记账错误的准确归因）；exit≠0 或 SHA 不符 → 按原授权停止并报精确原因，不重试、不绕行、不重跑审查

## Stop conditions
- 只读 ls-remote 权威查询返回值与授权目标 SHA 逐位一致即停止：不再 push、不再触发新审查、不再修补本地 refs/remotes（超出授权面）
- 退出码非零，或错误行针对远端 refs/heads / 含 `! [remote rejected]` → 不适用『本地记账』归类，停止并按授权报告精确原因
- 闸口以权威通道（如 review_admission status）实际撤销资格 → 立即停止，横幅免责逻辑不再成立

## Verification
- ls-remote 输出 SHA 与授权目标 SHA 逐位一致
- 受理行 old 段 == push 前远端 commit（受理时冻结的 push_remote_commit），new 段 == 本地被审 HEAD
- 错误行路径确在父仓 .git/refs/remotes/ 本地命名空间，且回执中无任何针对远端 refs/heads 的拒绝行

## Counterexamples
- exit≠0 或 stderr 含 `! [remote rejected]`、pre-receive hook declined、错误指向远端 refs/heads：真 push 失败，走 failed-oneshot triage，不得当作本地记账
- 回执没有 `old..new HEAD -> 分支` 受理行：exit 0 不足以断言远端成功（部分工具部分失败仍 exit 0），需按命令语义另行裁决
- 横幅来自准入系统权威撤销（review_admission status 变 FAIL）而非启发式提示：必须停下，不能以『横幅非凭据』豁免
- 非 git 工具 exit 0 + stderr 错误：没有 refs 命名空间可分类，需该命令自身的成功/失败判据
