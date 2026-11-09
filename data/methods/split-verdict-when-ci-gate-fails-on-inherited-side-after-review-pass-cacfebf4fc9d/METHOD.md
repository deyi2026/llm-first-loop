---
method_id: split-verdict-when-ci-gate-fails-on-inherited-side-after-review-pass-cacfebf4fc9d
name: split-verdict-when-ci-gate-fails-on-inherited-side-after-review-pass
description: 独立审查对候选已真实PASS后，在同一冻结工作树跑原版CI门禁仍以非零退出码终止时，第一未知量不是『审查结论错了』也不是『怎么修』，而是『阻断文件属于哪个子范围』：门禁自身输出的变更范围分区（ratchet/ledger 的 committed侧 vs uncommitted侧名单）与开局已冻结验证的候选路径集交叉，归属可机械读出。归到基线/继承侧→出分叉裁决终报：review PASS 与 gate FAIL 同时为真、候选未被证伪、本会话保持只读不修不重跑、合并闸仍阻断并把基线债移交所有权方；归到候选侧→才是候选缺陷回路。
aliases: 审查过了但CI挂了算谁的, 门禁失败归因基线还是补丁, review pass但ci gate失败, ci挂在没改过的文件, 过了审过不了门禁怎么收尾, 双裁决分叉报告
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4b0cdd2e-adc4-427d-a6e9-c88af3ddc5ca:0:460a6c1a4e1eac56f9de
evidence_refs: learning:learn:3baee64ac894
created_at: 2026-11-09T01:26:05.954631+08:00
updated_at: 2026-11-09T01:26:05.954631+08:00
---
## Trigger
审查已真实 completed+PASS 之后，按协议在同一冻结工作树执行原版CI门禁，job 真实终态为失败（exit≠0）；工作树形态为 HEAD=冻结基线、候选以已验证的 staged/worktree 改动存在，树内同时含基线提交侧与候选侧两类变更

## Discriminator
失败回执里门禁自带的变更分区名单（committed/继承侧 vs 本次候选侧）＋开局冻结回执中的候选路径集与指纹：阻断诊断点名的文件若只出现在继承侧名单、不在候选路径集内，归属即刻成立，无需任何额外调查

## Short path
- 以 job 真实终态取退出码，不用工具调用层 exit0 或等待超时代替
- 只读失败输出：确认失败停在哪一道门、后续阶段是否执行过（未执行就如实报无该阶段统计）
- 交叉门禁自打的变更分区名单与冻结候选路径集，给阻断文件定唯一归属
- 归属继承侧→分叉裁决终报：双裁决并列（审查PASS、门禁FAIL+归属证据），本会话只读、不修不重跑，合并闸仍阻断并移交基线债
- 归属候选侧→如实报候选缺陷，审查PASS不构成豁免

## Stop conditions
- 阻断文件归属唯一确定，且终报所需字段（真实exit、失败门、各阶段统计有无、归属证据引用）齐备即停
- 禁止因『审查已PASS』而重跑门禁、修改基线/脚本、或回头质疑开局冻结校验

## Verification
- 归属必须有两个独立来源同时支撑：门禁输出的分区名单 与 开局冻结回执的候选路径/指纹
- 终报退出码来自 job 终态回执，而非执行工具自身的 success 状态
- 终报同时携带两个裁决（审查PASS、门禁FAIL+归属），不得只报其一或互相覆盖

## Counterexamples
- 阻断文件在冻结候选路径集内：候选自身缺陷，走修复/复审回路，不能借『继承侧』脱责
- 门禁失败是环境性（工具缺失、版本不匹配、未到诊断阶段即崩）：归属分析不适用，先按环境故障上报
- 门禁输出不带范围分区且无冻结路径集可比：先用显式 diff 划分子范围，不凭文件名直觉归属
