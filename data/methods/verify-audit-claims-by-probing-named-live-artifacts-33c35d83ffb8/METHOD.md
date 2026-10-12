---
method_id: verify-audit-claims-by-probing-named-live-artifacts-33c35d83ffb8
name: verify-audit-claims-by-probing-named-live-artifacts
description: 收到对活系统当前/未来状态的审查断言（每条点名了可直读的证据载体：workflow 文件、远端 refs、run 列表、门禁脚本，并附修复选项）时：逐条改写成『点名主体+当前状态谓词』的问题，各用一次最小权威探针直读该主体；不从历史 evidence 库检索（存储记录只能证历史，本集实际出现关键词 miss 与 stale-block），也不探测同类型邻居主体（哈希比对先打到了 legacy remote，而 goal 与 tracking 行早已点名唯一目标仓库）。探针的拒绝/失败报文是下一层判别事实：用它证伪结构不可行的修复选项，让观测到的失败模式而非断言原文的选项清单决定处置；修复落地后用同一探针复测。与 fresh-read-before-finality 的边界：那条管自己下终局断言前重读权威记录，这条管裁决外来断言并选修复路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a5786c38-2507-4f58-a079-27d9e594ca12:471:397c8889d72446385612
evidence_refs: learning:learn:65d3f8f3fdcc
created_at: 2026-10-08T16:58:52.628930+08:00
updated_at: 2026-10-08T16:58:52.628930+08:00
---
## Trigger
一组关于活系统当前/推送后状态的审查断言需逐条裁决真伪并落地处置，且每条已点名证据载体（如 ci.yml/release.yml、远端 main、ratchet 门禁脚本）；或发现自己开始用 evidence 库枚举/换关键词重搜来验证这类断言，或对未确认归属的同类主体做比较时。

## Discriminator
断言谓词是预测/当前时态（『本次 push 后远端 CI 会显示红 X』），任何存储 evidence 元数据上即历史观测（freshness=unknown、currentness=unverified），不可能裁决它；同时断言与 goal 已点名唯一主体与载体（目标仓库、其远端 main、门禁脚本源码）——权威验证源只能是直接读这些命名主体的当前状态，且比较哈希必须对点名仓库而非恰好也存在的 legacy remote。

## Short path
- 恢复连续性最小集：读 goal/task frontier 确认上次停点，不扩查
- 每条断言改写为『点名主体+当前状态谓词』：目标仓库 main 最新 CI run 状态与失败步骤；进 main 的合规通道是否存在；点名仓库远端 main vs 本地 HEAD
- 每问一次最小权威探针：run list 直指点名仓库；ls-remote+rev-parse 比对同一仓库；读 workflow 与本地门禁脚本源码
- 把拒绝/失败输出当下一判别事实：最小合规尝试的拒绝报文（required checks 仅 PR 事件可产生）证明豁免类选项结构性不可行，转落地暂停协议并实测其窗口
- 按观测失败模式选修复（失败死在 ruff 且本地 ratchet 同时覆盖 pyright → 双 ratchet 同源锁面，而非只统一 ruff），推送后同一探针复测新 run

## Stop conditions
- 每条断言都取得来自点名权威主体的直接观测（run 终态、ref 哈希、门禁源码），不再追加确认性查询
- 修复已推送且同一探针已有可裁决的复测结果

## Verification
- 复测探针结果与修复预期一致（新口径 CI run 终态；重放父 commit 实测等于远端 main）
- 处置结论引用实测报文/退出码/失败步骤名，而非断言原文措辞

## Counterexamples
- 断言是纯历史问题（『上次为何失败』）且 evidence 库有新鲜一手记录——先查库更省
- 探针有副作用或成本（触发部署、消耗配额、改动共享状态）——直探活系统前先评估，不能无脑打探针
- 断言方已附可复核的一手证据（带 run id 与新鲜时间戳）——抽查即可，不必全量重测
- 断言未点名任何主体或载体（纯观点评价）——本方法无 anchor，应先索要可证伪事实再行动
