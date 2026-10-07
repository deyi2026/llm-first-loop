---
method_id: complete-range-hydration-before-durable-transcription-1e8c784264df
name: complete-range-hydration-before-durable-transcription
description: 当要把 evidence/工具回执正文逐字转写进持久工件（acceptance 判据、checkpoint、报告引文）时，读取目的决定读法：转写目的应一次用足够大的 limit 取到 range.complete=true（或按 next_start 恰好补一次），而不是先用默认小 limit 探测、发现截断后整轮重取。hydration 包络机械报告 complete/next_start/count==requested_limit，complete=false 即截断且常断在判据/基线数字中间；把 completeness 校验前置于转写，既省一轮调用，又防止把截断文本固化进 acceptance。仅需 gist（提醒时刻、存在性）时小 limit 截断读即为正确做法。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ba2daf39-ade3-4308-855e-bf3018c00381:215:f27285b0ebdb1e8e25fc
evidence_refs: learning:learn:cec4bda2cb2a
created_at: 2026-10-06T21:14:30.471840+08:00
updated_at: 2026-10-06T21:14:30.471840+08:00
---
## Trigger
即将对某条 evidence/回执做 ranged hydration 读取，且读取内容将被逐字或近逐字写入持久工件（如把多判据观测清单+基线数字写进 task acceptance）；或上一轮回执刚返回 complete=false 而下游工件需要全文。

## Discriminator
回执包络的机械完整信号（knowledge-at-time）：range.complete=false、next_start 非 null、count==requested_limit（本集首轮 5 个读取中 3 个在 200 字符处截断，T+24h 判据正文断在'② '处，基线数字位于未取回部分）；同时读取目的在调用前已声明为'取精确事实写 acceptance'，即全文是需求而非可选。

## Short path
- 声明本次读取目的：gist 还是逐字转写进持久工件
- 转写目的 → 每个目标 ref 一次用足够大的 limit 发起 hydrate（观测 server 接受 ≥3000 且 bounded_by_server_max=false），长度未知量由同一回执的 range 元数据解决
- 检查回执 range：complete=true 即可直接使用；complete=false 且需要全文 → 按 next_start/更大 limit 恰好补取一次
- 仅需 gist 的 ref（如 T+28d 提醒时刻）→ 接受截断读，不取全文，直接进入主流程
- 只从 complete=true 的正文向工件转写；核对每条转写结尾无半句/半条判据截断，停止

## Stop conditions
- 所需 refs 均 complete=true 且判据/基线数字齐全 → 写入工件并停止
- 仅需 gist 且已获得（时刻/存在性/相关性判断）→ 不取全文，继续主流程
- 探索阶段仅判断来源是否相关 → 小 limit 命中/未命中已足够决策
- 回执已 complete=true → 禁止再用更大 limit 重取同一 ref

## Verification
- 持久工件中每条判据/基线数字可追溯到一个 complete=true 的 hydration blob（含 blob_sha256）
- 转写文本结尾完整：count<requested_limit 或 complete=true，无中断 token/半条判据
- 工具调用数：转写类读取应单轮完成，不出现同 ref 换 limit 的第二轮重取（gist 读除外）

## Counterexamples
- 只需要点时：提醒时刻、存在性检查、相关性探测——小 limit 截断读就是正确做法，取全是浪费（本集 T+28d 回执保持截断是正确的）
- 源为无界/超长日志且只关心最新尾部：不应追求 complete=true
- 需要的是'最新值'而非'完整值'的并发写者终局断言场景：适用 fresh-read-authoritative-record-before-finality-claim（重读权威记录），不适用本方法
- 内容已知很短（complete=true 已见）：再发大 limit 请求是纯冗余
