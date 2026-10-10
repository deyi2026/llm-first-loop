---
method_id: audit-receipt-identity-before-chasing-reported-failures-d82a836d9dda
name: audit-receipt-identity-before-chasing-reported-failures
description: 当门禁/CI/作业回执或失败日志给出失败归因，而已确证的 provenance 事实与之冲突（被点名文件未被 intervening 提交触及、changed 文件计数与 git diff 对不上、基线数字与磁盘账本不符）时，先不要顺着报告内容追查“是谁引入的”；把回执本身当作待验证对象：抽取其自描述元数据（changed 文件清单/计数、工具版本、时间戳、基线总数）与仓库独立事实交叉核对。矛盾成立即判定回执不是本树/本版本的产物，停止追查它报告的诊断，改用权威、版本锁定的同一调用方式复现一份可信回执，只修权威回执指出的真实阻塞。该判断可把数十轮的提交/账本考古压缩为一两次核对加一次权威复现。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:64924088-0141-4a3a-87ee-81f09678620d:561:364c57ec319e57d7fce9
evidence_refs: learning:learn:56381ec046e3
created_at: 2026-10-10T13:20:22.854074+08:00
updated_at: 2026-10-10T13:20:22.854074+08:00
---
## Trigger
已读到一份声称失败的门禁/CI/作业回执或日志，且其中至少一项可与仓库独立事实立即比对：被点名失败文件是否被 intervening 提交触及、changed 文件计数、基线/账本总数、分析器版本。

## Discriminator
回执自描述元数据与独立仓库事实的矛盾：当时已知被点名的文件未被唯一 intervening 提交触及、与改动零 import 耦合（changed_file_diagnostics=0），而一次 git log/diff 即可证实其 changed 文件计数与真实不符——说明有问题的 artifact 是回执本身，而非被报告的代码。

## Short path
- 读回执，先抽取自描述元数据：失败清单归属、changed 文件数、基线数字、工具版本、时间戳（未知量：这次失败是否属于当前树/版本）
- 用一次 git log/diff 核对被点名文件的触及历史与当前真实 changed 文件数（未知量：回执元数据是否自洽）
- 元数据一致 → 回执可信，转入对报告失败项的常规调试，停止怀疑回执
- 元数据矛盾 → 判定回执不可信，停止追查其报告的诊断；用门禁脚本的实际调用方式、版本锁定地全树复现（未知量：真实阻塞是什么）
- 只修权威回执指出的真实阻塞，重跑门禁至绿，停止

## Stop conditions
- 取得权威复现回执，且其 changed 文件数与 git diff 实际一致（元数据自洽），真实阻塞已定位
- 若交叉核对一开始就一致，则回执即可信来源，直接进入失败项调试，不再审计回执

## Verification
- 权威回执的 changed 文件计数等于 git diff --name-only 的真实行数，与被证伪回执的数字构成硬矛盾记录
- 权威回执点名的失败在本地可复现，最小修复后重跑该门禁通过
- 权威回执的基线数字与磁盘账本一致

## Counterexamples
- 回执元数据与仓库事实一致（changed 清单、基线数字均吻合）：回执可信，直接调试报告的失败项，额外审计回执是浪费
- 被点名的失败文件恰好被最近的提交改过：第一假设是自己的变更引入，先读该提交 diff，不做回执身份审计
- 无可复现的权威调用方式（脚本或锁定版本不可得）：此时才退回按提交历史逐个排除的考古式定位
