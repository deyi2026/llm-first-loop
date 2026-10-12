---
method_id: jump-probe-oversized-single-line-blob-past-uniform-noise-66a24f77d981
name: jump-probe-oversized-single-line-blob-past-uniform-noise
description: 状态类回执被截断后从 evidence 恢复超大单行 JSON 时，不要前向等步长分页。本集 blob 长 37929 字符，generation_lag 审计噪声占前 ~24k；模型已自述「噪声占大头」，却仍按 2.6-3.4k 窗口顺读 5 次才抵达运行时事实段（~24.2k 起），4 窗纯噪声、约 15k 噪声字符进入上下文。当时已知的键序（admission_barriers→audit_signals→运行时事实在后）加上逐窗一致的元素 schema（{generation,lag_generations,target}，不含 pid/代码/restart_required/idle 任何目标字段）足以把噪声区整体划为跳过区：首窗直取尾部或二分噪声/目标边界，命中即停。判别必须字段级——元素含 feishu/learning 字样不等于含目标字段。可把 5 窗/15k 噪声压到约 2 窗。（本集另有 restart 参数契约失误，属另一类摩擦，不并入本卡。）
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:1040:0c4e9bc7483c69ba70e1
evidence_refs: learning:learn:fe7bcfe2c3a4
created_at: 2026-10-12T09:59:10.178967+08:00
updated_at: 2026-10-12T09:59:10.178967+08:00
---
## Trigger
需要从只能按字符区间取窗的超大单行 artifact（总长已知、数万字符）中定位少数目标字段；且回执前缀或首窗已显示存在元素 schema 统一、不含目标字段的已知噪声区（如审计 lag 数组）占据大头。

## Discriminator
取窗前已可观察：(1) hydration 元数据给出 blob 总长与单行性；(2) 首个回执已暴露键序——admission_barriers→audit_signals.generation_lag→…，运行时事实段位于噪声数组之后（即 blob 后段）；(3) 已见窗口内容全部是同一元素 schema {generation,lag_generations,target}，缺少 pid/代码/restart_required/idle 全部目标字段 ⇒ 该区间可整体跳过。三者共同把「任意窗口都可能有答案」缩成「目标段在噪声区之后的后段，从尾部探测」。

## Short path
- 若首次取回已声明 complete 且目标字段实际完整在手：就地解析，零分页
- 否则首窗直取尾部（start≈blob_len−窗宽），判定末段是聚合/运行时事实段还是仍在噪声区
- 尾部即目标段：回退半窗覆盖完整目标数组，一次读取提取 feishu/learning 基线（pid/代码/启动时间/restart_required/idle）
- 尾部仍是噪声：步长减半回退（二分）定位噪声/目标边界，再精读覆盖目标段的最小窗
- 基线字段齐备即停止取窗，转入执行（并行 restart 两目标）

## Stop conditions
- 目标字段已在某一窗口完整可见且无截断
- 权威替代来源使基线未知量失效（如控制器终态回执自带逐服务 verify 事实）

## Verification
- 提取的基线与后续权威回执互证：本例基线 restart_required=true/旧代码，重启后 verify=confirmed_ok、聚合快照 restart_required=false/lag=0，方向一致
- 确认所选窗口覆盖目标段完整边界（目标数组首尾元素均在窗内，无截断字段）

## Counterexamples
- 噪声数组本身即任务目标（如需统计各代 lag 分布或定位特定 generation 的 lag）：必须全读或精确索引，不可整体跳过
- artifact 小到一个窗口即可容纳：直接全读，尾部探测反而多付调用
- 工具原生支持按 key/正则检索 blob 内容：用检索替代位移猜测
- 「噪声」数组元素 schema 与目标字段有重叠可能（目标恰是数组内某条目）：先做字段级比对确认确实不含目标字段，才允许跳过
