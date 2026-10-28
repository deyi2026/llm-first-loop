---
method_id: tail-anchored-summary-harvest-after-authoritative-terminal-08f3d63af398
name: tail-anchored-summary-harvest-after-authoritative-terminal
description: 后台任务的终态（state/exit）已由 wait/回执权威证明后，剩余交付若只是少数具名汇总事实（门禁判定、xdist/串行复检计数、最终总结行），不要从 offset 0 顺序分页读完整份日志：依据已有预览中的日志结构（阶段标记 [k/N]、总结行在尾部）做一次尾部/锚点定向读取，至多一次有界补读；不重读已返回区间，相信 range 元数据（count=0/complete=true 即尽头），不二次探测空尾。exit 引用回执而非日志文本，读不到的字段如实标注缺失。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ce9749f0-3a3e-4ade-ac65-3da5184f6f21:0:a8c9b090e9f9ab0d53ef
evidence_refs: learning:learn:b9da2de55062
created_at: 2026-10-18T23:40:44.843936+08:00
updated_at: 2026-10-18T23:40:44.843936+08:00
---
## Trigger
后台 job 已通过 wait/终态回执取得权威终态（state=completed、exit code 已知），而用户点名的剩余交付物只是日志中少量汇总事实（各阶段判定行、总计数、串行复检计数、最终结论行）

## Discriminator
摩擦发生前已知：①终态与 exit 已由回执证明，无需再从日志推断；②首次 job_output 预览已声明日志有界（如“输出（566 行）”）且可见阶段结构（[1/5]…[5/5] 门禁），说明用户要的计数/总结行位于尾部；③开头区间（前 4000 字符）已在上下文中，重读 start=0 是零信息动作；④每次区间回执自带 complete/next_start 元数据，count=0 即已证明到达日志尽头

## Short path
- 用已有终态回执直接满足 terminal/exit 交付项，不再为确认已知事实读日志
- 从既有预览确定用户点名字段的日志锚点：阶段制 gate 脚本的汇总/计数行在尾部
- 只对尾部（或锚点附近）做一次较大区间读取，提取最终判定行与 xdist/串行复检计数；跳过已返回的开头区间
- 若该窗口缺某个点名字段，用 next_start 做至多一次有界补读，而非从头顺序分页或全量扫描
- 信任 range 元数据：任一区间 count=0 或 complete=true 即为日志尽头，不再追加空尾探测
- 逐项对照用户点名计数清单，齐全即停并报告；exit 引用回执、计数引用实际读到的日志区间

## Stop conditions
- 用户点名的每个汇总字段都已从同一 blob_sha256 的已读区间取得，且 exit/state 已由终态回执证明
- 区间回执显示 complete=true 后，不得再对同一日志发起追加探测读取
- 发现 exit≠0、终态不确定、或 blob_sha256 漂移时，停止汇总提取，转为定位失败根因或如实报告证据并停止

## Verification
- 报告中的 exit/state 引用自 wait 终态回执，而非由日志文本倒推
- 所有计数行均来自实际读取到的区间，且同属一个 blob_sha256（日志未被截断或替换）
- 交付字段与用户点名清单一一对应；未读到的字段如实标注缺失，不用记忆或推断填数

## Counterexamples
- exit 非 0 或终态不确定：失败 traceback 可能在日志任意位置，仅读尾部会漏掉根因，应改为按错误标记锚定读取
- 用户要求全量日志审阅（如列出所有警告、逐门禁取证）时，完整分页本身就是任务，不适用本方法
- 所需汇总行实际位于日志开头（如执行计划头、配置回显），或日志无 complete/next_start 元数据且持续增长时，尾部锚点与一次性探测失效
