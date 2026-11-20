---
method_id: reissue-managed-admission-when-invocation-tuple-changes-b473c9591407
name: reissue-managed-admission-when-invocation-tuple-changes
description: 用户纠正导致受管动作（如 push）的调用面变化后，已有 PASS 资格不可默认复用：门禁按审查时的精确 (command, workdir) 元组绑定资格，规范化目标哈希与候选树摘要相同也不豁免。动作前逐字段比对当前调用与签发时元组；不一致就直接以当前元组重新发起受管审查，跳过注定被元组不一致类阻断拦下的复用重试；逐字段相同才按原资格原样重试。同一树摘要两轮结论冲突时按 fail-closed 以 REVISE 为准。终态 PASS 后以完全相同元组执行并核远端结果；REVISE 则冻结、落账、报告待授权，绝不绕过门禁。
aliases: 换了个写法推送就被拦下要重新过审, 上次的审查通过这次还能直接推送吗, 纠正参数后旧批准失效, 同哈希不同写法门禁不认, 按当前目标重新受管审查
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d901b48e-25bf-45f0-a33f-23eaa879ddc3:137:603541431f87c1883226
evidence_refs: learning:learn:4be84542bbc7
created_at: 2026-11-19T00:15:45.206585+08:00
updated_at: 2026-11-19T00:15:45.206585+08:00
---
## Trigger
受管准入类动作（如 git push）此前已获 PASS 资格，但用户纠正或自查后本次调用的结构化字段发生了变化：显式补传/修改 workdir 参数、改写 command 原文（如去掉命令内 cd、去掉退出码掩盖后缀）；而规范化目标哈希与候选树摘要均未变。

## Discriminator
重试前已可见：用户纠正明确写明『资格闸精确绑定、必要时按门禁重新受管审查』；且本次调用的 (workdir, command) 与旧资格签发时的调用面逐字段不同——该事实已足以预测复用旧资格会得到元组不一致类阻断，无需先试错。

## Short path
- 读误发/已执行动作的回执，确认有无副作用（退出码、目标仓库 HEAD、脏文件计数），先止损再纠正
- 逐字段比对当前调用的 (workdir, command) 与旧资格绑定元组；任一不同即判定旧资格不可复用
- 以当前精确元组重新发起受管审查（review_admission start），冻结 SHA/ref/树摘要，按回执自带的等待协议有界轮询
- 终态 PASS → 用逐字段相同的元组执行动作并核远端结果；REVISE/FAIL → 不执行，落账并报告，等用户授权修复分级问题

## Stop conditions
- admission 返回终态资格即停止轮询分支
- PASS 执行后结果核验一致（如远端 SHA=冻结的 push_src_commit）即收口
- 收到自带修复指引的阻断回执（如元组不一致）时按其差分转重审，不做参数试错、不绕过
- 同一 candidate 摘要两轮结论冲突时，按 fail-closed 以更严格的 REVISE 为准，冻结不执行

## Verification
- 新资格回执冻结字段（push_src_commit、candidate_sha256、目标 ref）与当前现场一致
- 执行回执的退出码未被 echo 后缀掩盖；push 后用 ls-remote 核远端 SHA 与冻结值一致
- REVISE 时确认未 push、未建 PR，main 与其他 lane 零改动

## Counterexamples
- 当前调用与审查时逐字段相同且树摘要未变：旧资格有效，直接原样重试；重新 admission 徒耗审查预算
- 门禁文档明文按内容/规范化哈希绑定而非调用面：改写法不影响资格，按其声明的绑定语义处理
- 阻断原因是候选内容变更（新提交、树摘要不同）而非元组不一致：走新提交+新审查管线，与本方法无关
- 无准入绑定的普通工具调用（读文件、查状态、本地校验脚本）：不存在资格复用问题
