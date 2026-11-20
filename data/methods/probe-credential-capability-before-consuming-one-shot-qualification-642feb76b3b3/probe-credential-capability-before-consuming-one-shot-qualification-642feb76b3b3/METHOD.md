---
method_id: probe-credential-capability-before-consuming-one-shot-qualification-642feb76b3b3
name: probe-credential-capability-before-consuming-one-shot-qualification
description: 审查PASS后、发起消费一次性资格的执行调用（受管git push等网络动作）前，先用只读零成本探针解析环境的执行能力未知量：remote URL scheme、credential.helper、git credential fill能否非交互取凭据。判别依据（当时在场）：回执横幅声明沙箱有已知降级（宿主集成设施可能失败）、任务书明示本项目从未有过成功push回执（上一Run资格被参数形态错误烧掉，push从未投递）。注意ls-remote读远端成功≠写凭据可用。探针失败→不签发资格，直接向用户报告换SSH/预置凭据/手动推送选项；探针通过→照常start→PASS→push一次执行。与『参数形态预校验』卡互补：那张管调用合同，本卡管环境能力，两者都是签发前的免费未知量。
aliases: git push 提示输入用户名, Device not configured 推送失败, 审查过了push还是失败, 一次性资格白烧了, 先看remote是https还是ssh再推, 沙箱里keychain凭据拿不到
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:37596905-cd68-421a-ad2d-d6dcf2ffd14f:131:676fab23f5481e1762e3
evidence_refs: learning:learn:0aa893527474
created_at: 2026-11-19T17:45:57.303653+08:00
updated_at: 2026-11-19T17:45:57.303653+08:00
---
## Trigger
已取得review PASS、即将调用执行工具消费一次性准入资格执行网络类动作（如受管git push）；环境为声明含已知降级的沙箱，且无本动作类在此环境的历史成功回执。

## Discriminator
push的传输/凭据路径是未被证明的未知量，但在既定的只读核对步骤内可零成本解析（git remote -v、git config credential.helper、git credential fill探针）；而资格是一次性的，签发后环境失败即烧掉资格并强制下一Run从头重审。当时在场事实：每条回执横幅列明沙箱已知降级（ps EPERM等宿主集成设施失败先例）、任务书明示上一Run的PASS资格已被消费且push从未实际执行。

## Short path
- 在既定只读核对步骤追加 git remote -v 与 git config --get credential.helper（解析未知量：push依赖哪种传输协议与凭据源）
- 若origin为HTTPS：加一次零副作用 git credential fill 探针（解析未知量：沙箱内能否非交互取得该host凭据）
- 探针通过→按原计划 start→有界status轮询至PASS→仅argv形态push一次
- 探针失败或凭据源无法非交互提供→不发起admission start、不消耗资格，向用户报告SSH remote/预置Keychain凭据/用户手动推送三选项并停止
- push完成后只读ls-remote核验远端分支SHA==冻结push_src即停止

## Stop conditions
- 凭据探针失败或凭据源无法非交互提供→不签发资格，转用户决策
- 本环境已有同类push成功回执或remote为已验证SSH→能力已证明，跳过探针直接走原流程
- push执行完成且远端SHA核验一致→停止，不再追加调用

## Verification
- execute_command之前，存在一份零副作用探针回执证明非交互凭据路径可用（或SSH remote已配置且有成功先例）
- push后只读ls-remote回执显示远端分支SHA与冻结push_src一致
- 资格账本一致：一次PASS对应一次成功投递，不存在granted=1/consumed=1但push未执行的状态

## Counterexamples
- remote为SSH且本环境有历史成功push回执→凭据能力已证明，直接执行，不加探针
- 动作纯本地无网络/凭据依赖（如本地pytest、只读git操作）→环境能力探针无意义，只需调用参数合同检查
- 用户明示已知凭据缺失仍要求照常执行或预期人工交互→遵用户指令，不套用本方法
- 探针本身有副作用或会被闸计为push（任何写操作、真实push、可能被门控的--dry-run）→不得用作探针
