---
method_id: opaque-aggregate-hash-issuer-not-scheme-guessing-93660dd52f9f
name: opaque-aggregate-hash-issuer-not-scheme-guessing
description: 任务书引用一个冻结/聚合 SHA 要求核对（如候选指纹 8802…），但当前上下文没有它的计算方案文档，且已读到与它不一致的本地聚合值（state 里的 candidate_sha256、v1/v2 两版清单）时，第一未知量是“这个 token 由谁签发、由哪条权威途径重确认”，而不是“用哪种本地管道把聚合凑出来”。一次读 task_state/checkpoint 同时定位签发者与逐文件清单；用逐文件 sha256 完成内容对账；把聚合 token 的复验留给签发工具的下一次正式调用。禁止对同一批指纹串反复换聚合管道枚举试图命中——那是无界搜索。
aliases: 哈希凑不出来就换思路, 冻结指纹对不上, 逐文件sha256对账, 先找哈希签发人, 别猜哈希怎么算的, 指纹反推卡住
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:774:bc347963742a08f58350
evidence_refs: learning:learn:3d59f0ee1afe
created_at: 2026-11-07T17:50:10.757695+08:00
updated_at: 2026-11-07T17:50:10.757695+08:00
---
## Trigger
任务/用户引用某聚合指纹或冻结 SHA 并要求『核对仍为 X』，但当前材料未给出该值的聚合方案；同时仓库状态里存在逐文件指纹清单以及签发该 token 的工具记录（checkpoint/task_state/准入回执）

## Discriminator
已读状态里出现与用户引用值不一致的本地聚合（candidate_sha256≠X），且逐文件清单存在多个版本（v1/v2 内容不同），同时准入记录显示该 token 属于某个以 scope=patch 启动的审查准入 child——三者共同证明该值是『方案+冻结版本绑定』的外部 token，本地枚举聚合管道不可能稳定命中

## Short path
- 按任务步骤完成预检（goal/service 状态/进程与 HEAD 探针）
- 一次读 task_state/goal checkpoint：同时取得候选路径构成、最新逐文件清单位置、token 签发者是谁
- 用最新清单做逐文件 sha256 对账（一段脚本一次完成），全部匹配即内容零漂移
- 在 checkpoint/恢复锚点中把聚合 token 标注为签发者持有，由其下次正式调用（如新 review_admission start）重确认
- 按原步骤继续受控重启等后续动作，不因聚合值未在本地复现而新增探测

## Stop conditions
- 逐文件对账全部匹配，内容零漂移，进入下一任务步骤
- 任一文件指纹不匹配→停止并报告漂移，不进入重启/审查
- 同一批指纹串已尝试第二种聚合管道仍未命中→立即停止反推，转找签发者

## Verification
- 逐文件 sha256 与最新清单逐项一致
- 聚合 token 由签发工具下次调用的回执（或显式 verify 接口）确认，而非本地复算成功

## Counterexamples
- 任务明确给出聚合方案（排序+拼接+再哈希）时，直接按方案一次复算即可，无需找签发者
- 目标是单文件哈希时，直接 shasum 对账，不存在方案歧义
- 签发工具提供显式校验接口时，直接调用校验，不要等下一次 start 才确认
- 逐文件清单缺失且签发者无法定位时，才退回用精确哈希串做工作区搜索或向用户澄清来源
