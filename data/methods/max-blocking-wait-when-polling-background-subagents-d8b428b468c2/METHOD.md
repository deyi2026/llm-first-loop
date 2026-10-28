---
method_id: max-blocking-wait-when-polling-background-subagents-d8b428b468c2
name: max-blocking-wait-when-polling-background-subagents
description: 后台 child 派遣后的等待与收口协议：轮询工具回执若显式广告阻塞等待区间（如 wait_seconds=0..30）并提示'可继续父级工作'，则每次轮询都带最大等待值阻塞，间隙填入父端待办，而非零等待紧循环重查；终态回执若 result_truncated=true，先用其内嵌 evidence_ref/recovery_handle 分页水合完整原文（blob_sha256 一致、complete=true）再引用裁决；落盘回执用常规结构化参数（长负载避免 raw-arguments 逃逸致必填字段丢失），写后复核冻结面不变。
aliases: 轮询子代理结果 别空转紧循环, wait_seconds 拉满阻塞等, result_truncated 先水合全文, recovery_handle 逐页翻完, blob_sha256 一致才敢引用, 等子代理别一直刷
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25393690-39c2-43d8-b50f-3157a58aaea2:126:202db36803dbb3bbc818
evidence_refs: learning:learn:254706db6663
created_at: 2026-10-15T07:42:11.966908+08:00
updated_at: 2026-10-23T05:52:03.869476+08:00
---
## Trigger
已 spawn 后台 child/subagent 并需等待其真实终态（如轮询 subagent_result）；首轮回执显式给出可阻塞等待参数区间（wait_seconds 上限>0）并提示可并行父级工作/steer/稍后查询。

## Discriminator
spawn 回执本身已印出'查询/等待: subagent_result(wait_seconds=0..30)'与'可继续父级工作'——说明零等待立即重查是可避免的空转，且等待间隙有明确可填充的父端动作；后续每次未结算回执都重复确认这一事实。

## Short path
- spawn 后第一次 subagent_result 直接带 wait_seconds=上限阻塞等待终态，而不是立即零等待查询
- 返回未结算时，先做可并行的父端只读待办（回执目标文件名占用预检、落盘命令与报告骨架准备），完成后再发起下一次最大阻塞等待
- 终态返回先查截断标志：result_truncated=true 时用回执内嵌 evidence_ref/recovery_handle 分页水合（核对各页 blob_sha256 一致）直到 complete=true
- 完整文本中裁决字段（PASS/REVISE/BLOCK、P0/P1/P2、child_id、候选SHA）齐全后才落盘：用结构化参数而非 raw-arguments 逃逸封装长命令，先确认目标文件不存在、绝不覆盖
- 落盘后复核冻结面（diff 字节数/SHA/文件数）与派遣前一致，旧文件未动，然后报告真实终态

## Stop conditions
- child 终态且回执完整（或已水合至 complete=true），裁决所需字段全部在场
- 确需立即 steer/cancel，不能继续阻塞等待
- 远超预计时长仍未结算：停止轮询转为主动 steer 或上报，而非无限空转

## Verification
- 轮询次数 ≤ ceil(预计时长/等待上限)+1，明显少于零等待重复轮询（本集对照：13 次 vs 约6次）
- 引用 child 裁决前确认文本来自 complete=true 的完整恢复而非截断片段
- 落盘/报告后冻结面复核：staged diff 字节与 SHA、文件计数不变，仅新增声明文件

## Counterexamples
- 轮询工具不提供阻塞等待参数（回执无 wait 区间）——只能做带退避的轮询，本方法不适用
- child 运行中需高频 steer 或监控中间进度——长阻塞等待会延迟干预时机，应短等待或事件回调
- child 预计秒级完成——单次最大等待即可，无需构造填充工作
- 终态回执短且未截断——跳过水合步骤直接收口
