---
method_id: live-run-loop-triage-and-steer-channel-rescue-3d75908f33cc
name: live-run-loop-triage-and-steer-channel-rescue
description: 用户指着一个正在运行的 agent run/会话说“有问题/卡住”时，先分层分诊再干预：(1) 用事件计数判定基础设施健康——provider 交换若连续 settled success，则排除中间件/传输层，问题定位到 run 行为层；(2) 对疑似循环做量化：同一目标、逐字相同的错误回执、固定节奏连续出现 ≥3 次 ⇒ 判定为确定性失败循环，而非瞬时故障；(3) 不继续被动观察、不重启进程，改用系统提供的用户 steer/interject 通道注入带停止条件和备选方案的明确指引（端点形状不确定时先查 schema/路由定义再调用，避免向猜测的端点先发一枪）；(4) 一个有界等待周期后验证循环已断且 run 到达终态，再汇报。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:410:7a7403db37d9feed365b
evidence_refs: learning:learn:dcdde3e4af05
created_at: 2026-10-11T18:06:42.382198+08:00
updated_at: 2026-10-11T18:06:42.382198+08:00
---
## Trigger
用户报告某个 live agent run/会话异常（卡住、反复失败、无进展），需要诊断根因并让 run 恢复推进或正常收口。

## Discriminator
分诊当时已可见的事实：(a) resume 点之后 provider 交换计数全部 success ⇒ 基础设施健康，问题在行为层；(b) 工具回执对同一目标返回逐字相同错误文本、连续 ≥3 次、间隔固定 ⇒ 确定性失败（重试无意义）；(c) 同一内容存在已成功的替代通道（如浏览器页已打开且快照成功）⇒ 干预指引可给出明确备选。三者齐备即可确定‘不是 bug 而是死循环、且可安全打断’。

## Short path
- 读会话/队列状态与事件尾部（未知量：run 是否活着、队列项终态）
- 对 resume 点后事件分类计数：provider 成功率定 infra 健康、按工具统计失败（未知量：问题是 infra 还是行为）
- 量化疑似循环：失败次数、首末时间、错误文本是否逐字相同（未知量：确定性循环还是瞬时故障）
- 确认 ≥3 次逐字相同失败且 infra 健康 ⇒ 停止观察，走 steer/interject 正规通道注入指引（含停止条件与二选一备选）；端点参数不确定先读 schema 定义
- 等待一个有界周期（约一轮），验证循环已断、run 到终态，再向用户报告并附计数证据

## Stop conditions
- infra 计数出现真实失败/超时 ⇒ 切换到根因修复路径，不给远端 run 注入行为指引
- 重复阈值未达（<3 次）或每次错误文本不同 ⇒ 继续观察一轮，暂不干预
- 插话后一个有界周期内循环未破 ⇒ 升级处置（暂停/重启 run），不再干等
- run 已正常收口或用户只要诊断不要处置 ⇒ 只分诊汇报，不插话

## Verification
- 插话通道回执状态与事件流中指引实际注入时间戳一致
- 注入后下一轮工具回执不再出现该确定性失败，run 收敛到终态（completed 或等价）
- 向用户报告引用具体计数（连续失败次数、交换成功率、终态时间）而非主观判断

## Counterexamples
- provider 交换本身出现 settled failure/超时 ⇒ 是基础设施问题，应走最小修复，套用本方法会误导归因
- 失败仅 1-2 次且错误文本持续变化（换 UA、换异常类型）⇒ 可能瞬时或自愈中，打断反而丢失信息
- 无 live run 或用户仅要求读状态报告 ⇒ 无干预对象与授权，只做只读分诊
