---
method_id: tail-first-summary-retrieval-from-range-addressable-job-logs-0d000fd8d836
name: tail-first-summary-retrieval-from-range-addressable-job-logs
description: 从已完成的大的 job 输出中找一个终态事实（最终通过数、deselected、耗时、完成时间戳）时，先做 token 归属判定：结果类数字由运行产生、只会出现在日志末尾，grep 生产脚本的必然落空（脚本里只会有阈值/基线类数字）。然后利用水合回执自带的 range 元数据（start/next_start/complete），一次性请求最后一个区间，而不是从中段开始盲走多个区间。若尾部没有汇总行，转向检查调用 flag（如 quiet 叠加吞掉 'N passed'），而不是继续换区间读。
aliases: 去日志末尾找测试汇总行, 别在脚本里grep结果数字, 大输出里找passed总数, 按区间水合先取尾部, 结果计数在log不在脚本
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:73172f2a-c1f6-4868-9611-d4af1d463c48:3132:be1360d9a2cef80b0e59
evidence_refs: learning:learn:de9dd20626eb
created_at: 2026-11-03T23:40:39.447794+08:00
updated_at: 2026-11-03T23:40:39.447794+08:00
---
## Trigger
需要在已完成 job 的大输出（数百行/数万字符、按 char range 水合，回执带 range 元数据）中定位终态汇总事实：通过/跳过计数、总耗时、完成时间戳、最终 verdict 行

## Discriminator
token 归属 + range 元数据：『N passed / deselected / (Ns) / 完成时间』是 run-produced 汇总行，pytest 类运行器把它打印在输出最末尾，生产脚本里必然 grep 不到；同时回执已给出 next_start 与 complete:false，未读尾部是可直接寻址的有界区间——这两点在当时任一次水合回执里都已可见

## Short path
- 判定 token 归属：结果类汇总 token 属于 job 输出日志尾部，不属于脚本/配置 → 跳过对 scripts/*.sh 的结果数字 grep
- 从任一水合回执读 range 元数据（start / next_start / complete:false），推知未读尾部的位置与量级
- 一次性请求最后一个区间（约末 4-8KB），直接取得汇总行（计数+耗时）与完成时间戳
- 与 job 元数据（state=done / exit=0 / 时间戳）互证后停止；若尾部确无汇总行，改查运行 flag（quiet 叠加吞汇总行的历史教训），不再请求中段区间

## Stop conditions
- 已从尾部区间直接读到目标汇总行，且与 job 元数据（exit=0、完成时间）一致即停，不再请求额外区间
- 确认本次运行根本不打印汇总行（flag 吞掉）后，转为修 flag 问题，停止在旧输出里继续寻址

## Verification
- 汇总行中的计数与 job 元数据（state=done、exit=0、完成时间）互相印证
- 确认汇总行取自本次 run 的输出（对齐同一 blob_sha256 / range 链），不是历史运行的陈旧片段

## Counterexamples
- 目标事实是日志中段事件（首个 traceback、某分段的计数、早期 404）——尾部锚定会漏掉，应按段落标记或日志内定点检索
- 数字本身是配置/阈值类（ratchet 基线、预算上限），由脚本或配置文件拥有——此时 grep 脚本才是正确目标，尾部读取反而错
- job 仍在流式输出、未到终态——尾部内容不稳定，先等待 state=done 再寻址
- 回执不提供 range/extent 元数据——无法寻址尾部，只能改用日志内搜索工具
