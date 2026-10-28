---
method_id: anatomy-triage-failed-gated-oneshot-then-readonly-aftermath-399722b02df3
name: anatomy-triage-failed-gated-oneshot-then-readonly-aftermath
description: 在带审查准入闸的 Host 中，唯一被允许的强保护命令（gated git push / 对外发布）首次执行即失败，且回执同时混有治理提示横幅与真实命令输出时，判定顺序按回执解剖：有真实退出码+原生 stderr ⇒ 命令已实际执行并在工具层失败，自述『非通过凭据』的横幅不是驳回裁决；再把 stderr 机制映射到任务枚举的 STOP 类（could not read Username / Device not configured = 非交互缺凭据；403 / non-fast-forward = 远端状态类）；最后用一次只读 ls-remote 对照预期 base，确认干净失败且无并发移动后按规则停止，不重试、不绕过凭据。另注意：只读成功不证明写凭据存在（公开库匿名可读）。
aliases: gated push失败 exit 128 could not read Username怎么办, 准入横幅说资格未核验算不算被拒, 唯一一次push失败先ls-remote看远端再停, 只读通不代表写有凭据, Device not configured 非交互git缺凭据, 闸控命令失败后STOP条件归类
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5c5db160-1103-401e-a2ef-b8ae07b607e6:1:bafdb1c201a509bb6de7
evidence_refs: learning:learn:35d249f509ed
created_at: 2026-10-27T13:11:30.577703+08:00
updated_at: 2026-10-27T13:11:30.577703+08:00
---
## Trigger
准入/审查闸控流程中，唯一被允许的强保护命令（如 gated git push）在其仅有的一次执行中失败；失败回执同时包含告示性闸横幅（如『审查资格未核验』）与真实命令输出（退出码+stderr）；任务书已枚举 STOP 条件（凭据缺失/远端分支移动/审查驳回/Host 拒绝等）且禁止重试与扩权。

## Discriminator
回执解剖学：存在真实进程退出码（如 128）与工具原生 stderr ⇒ 命令确实执行了、失败发生在工具层而非闸层；明确自述『本行不是审查通过凭据、执行状态以本回执为准』的横幅只是观测提示。stderr 为 fatal: could not read Username + Device not configured ⇒ 非交互环境无 TTY 且无 credential helper 供 Credential ⇒ 属『凭据缺失』STOP 类，不是审查驳回也不是 Host 拒绝。

## Short path
- 失败时先做回执解剖：有真实退出码+原生 stderr ⇒ 工具层失败；按 stderr 机制分类，不按横幅措辞分类（自我免责声明的横幅不是裁决）。
- 把机制映射到任务枚举的 STOP 类：用户名提示/ENXIO → 凭据缺失；403/受保护分支/non-fast-forward → 远端权限或拓扑状态类；无退出码/命令未执行 → 闸层驳回，回资格流程。
- 执行恰好一次只读状态检查（git ls-remote 目标 ref），对照事先声明的预期 base：相等 ⇒ 干净失败且远端未被并发移动；任何其他值 ⇒ 二次异常，仍不重试，直接按异常上报。
- 按 STOP 类停止：不重试、不换 SSH/token 等任何绕行；报告实际退出码、stderr 机制原文、只读证据，以及唯一剩余差量（本集：仅差一次 push，卡点只有凭据）。
- 禁止用事前只读探针预测写权限：公开仓库匿名读成功不能证明 push 凭据存在，写凭据只在写时才可观察。

## Stop conditions
- 已归入某个枚举 STOP 类，且只读检查显示远端 ref 仍等于预期 base（干净失败、无落地、无并发移动）→ 停止并如实报告。
- 只读检查显示目标 ref 处于非预期值 → 按『远端分支移动/异常』类上报，仍不重试、不自行恢复。
- 在用户提供凭据或变更授权之前，受保护命令后续执行次数为 0。

## Verification
- git ls-remote 目标 ref 输出等于任务书预先声明的分支 base（证明 push 未落地且远端未被他人移动）。
- 报告中的退出码与 stderr 与回执逐字一致；失败分类由 stderr 机制命名，而非由横幅措辞推断。
- 自查：失败之后受保护命令执行 0 次，无任何凭据绕行/路径改写/命令改参尝试。

## Counterexamples
- 回执没有退出码、或命令被标记为被 Host 阻止/拒绝 → 这是闸层驳回而非凭据问题：应回审查资格流程重取 PASS，不要按缺凭据分类（stderr 可能根本不存在）。
- stderr 是 403 / 受保护分支 / non-fast-forward → 远端权限或拓扑类问题：只读检查须同时对照预期 base 与本地祖先关系，与凭据无关，不该报成 credentials missing。
- 动作本身幂等或只读，或任务明确授权失败后重试 → 『一次只读检查后即停』纪律不适用，可分类后修正重试。
- 不能用事前 ls-remote 成功作为 push 会成功的证据：公开库匿名可读，写凭据只在写时才暴露；反之一次 ls-remote 预检也预测不了本次失败。
