---
method_id: confirm-inherited-root-cause-by-error-signature-not-exit-code-42cb74b685aa
name: confirm-inherited-root-cause-by-error-signature-not-exit-code
description: 接手/续跑诊断任务时，继承的根因断言常附带"可复现的失败信号"（如退出码 71）。复现出同码≠确认：同一退出码可能来自探针自身失效——载荷二进制不存在（execvp failed）、解释器不匹配等。确认前比对两件事：stderr/错误体是否点名断言的具体失败机制（如 sandbox_apply/Operation not permitted，而非 execvp failed/No such file），以及探针载荷在当前主机是否真实存在。码同而签名异即探针假阳性：换已验证存在的载荷重跑后再归因；修复落地时把归因谓词写成签名匹配+载荷校验，并为"载荷缺失"单独钉回归测试。本集借此推翻了"宿主嵌套致 exec 全线 71"的流传误判（实为 /bin/true 不存在）。
aliases: 退出码撞车, 探针假阳性, 同码异因排查, 先查探针载荷存不存在, 看 stderr 归因不是看返回码
status: candidate
source_model: deepseek/deepseek-flash
source_episode_refs: episode:7e91da8b-4d11-4df5-84fc-7666790cb2fb:1006:f55419103cf9a6eddb8a
evidence_refs: learning:learn:95fdf695da82
created_at: 2026-11-09T17:45:46.573398+08:00
updated_at: 2026-11-09T17:45:46.573398+08:00
---
## Trigger
复现继承的诊断结论以确认根因，且匹配信号是粗粒度退出码/错误码；探针一次运行即"完美复现"预期症状时尤其危险。

## Discriminator
stderr/错误体命名的失败机制是否与断言机制一致（execvp failed/No such file ≠ sandbox_apply/Operation not permitted）；探针载荷工件在当前主机是否真实存在（一条 ls/which 即可验证）。

## Short path
- 先用现行面一次真实调用证伪继承症状是否仍存在（本会话首条 exec 已 exit 0，"exec 全线不可用"已过期）
- 探针输出必须带 stderr 全文，退出码与签名一起比对，不做只看码的匹配
- 码同签名异 → 查载荷存在性 → 换已验证存在的载荷（/usr/bin/true）重跑，再归因
- 若仓库其他分支已有同修提交，先评估移植其谓词设计而非重写
- 修复中的归因谓词写成 stderr 签名匹配+载荷校验，并为载荷缺失路径钉回归测试

## Stop conditions
- stderr 签名与断言机制一致且载荷前置已验证 → 确认根因，停止怀疑探针，进入修复
- 换载荷后原症状消失 → 判定探针假阳性，撤销该归因并如实记录新事实

## Verification
- 用正反两个已知用例对照：机制应触发时的最小复现（如外层沙箱包裹→sandbox_apply 拒绝）与不应触发的用例（已验证载荷→rc=0）
- 归因谓词对"execvp 失败"与"权限拒绝"两类同码情形分别有钉死单测

## Counterexamples
- 退出码本身唯一且文档化（如 grep exit 1=无命中）→ 码匹配即可确认，无需签名比对
- 失败对象是生产路径本身而非合成探针 → 真实失败即证据，不存在探针载荷失效问题
- stderr 被采集链路吞掉且无替代可读通道 → 只能退出码+载荷存在性双查，不强行签名归因
