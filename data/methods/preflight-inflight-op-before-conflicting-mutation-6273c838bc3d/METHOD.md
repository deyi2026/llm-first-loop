---
method_id: preflight-inflight-op-before-conflicting-mutation-6273c838bc3d
name: preflight-inflight-op-before-conflicting-mutation
description: 对异步互斥管理的共享资源（重启/部署通道）发起同类新变更前，先用权威终态入口查在途操作与 barrier 归属：若同目标已有受理后在途单且其绑定已被推进的 desired 证伪，只推进 desired，不立即受理新操作（必被 barrier 拒并留下噪音 failed 台账），把销账与再受理留到 barrier 释放后。核心：把自己刚写下的操作纪律（受理≠完成、终态核对入口、CAS 先 publish 再 restart）立刻套用于自己的下一个动作，而不是先行动、再靠被拒回执发现冲突。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:2090:cea089d6571b7e219832
evidence_refs: learning:learn:e57c6a060e22
created_at: 2026-09-24T03:53:32.124844+00:00
updated_at: 2026-09-24T03:53:32.124844+00:00
---
## Trigger
已知晓或刚写入某共享异步通道的操作纪律（互斥 barrier、受理≠完成、终态核对三入口），且已知同目标存在受理后在途操作，而自己正要发起同类新变更操作（如 publish 后立即受理 restart）时。

## Discriminator
发起时刻已存在的两条事实：① 同目标上一操作已受理仍在途（waiting_for_requester_exit），互斥 barrier 必被其持有；② 刚写入权威文档的纪律已给出 status/台账/事件流终态入口与『先推进 desired 再受理』顺序。这两点足以把『直接发起新操作/干等/销账/推进』缩成『先查在途单终态与 barrier 归属再决定』。

## Short path
- 以权威回执验证用户交付物完成（skill 更新→commit 回执），此为任务主体。
- 发起任何新的变更调用前，先经一个终态入口查同目标在途单：未知量=barrier 归属、在途单绑定代与状态。
- 若在途单持有 barrier 且其绑定已被新 desired 证伪 → 仅 publish 推进 desired，不立即受理新 restart（会被拒、产生噪音 failed 记录）。
- 写出预期 fail-fast 结果与下步销账→再受理的顺序，留待 barrier 释放后执行；若需确认执行语义，只沿回执中的失败 detail 定位对应代码分支做一次定点核验，不做全文件宽 grep。

## Stop conditions
- 用户所需交付物已被权威回执（commit/publish 回执）验证。
- 在途链路状态已从权威台账确认，且未因自己的新调用产生未解释的 failed 记录。

## Verification
- 新变更调用之前存在一次 status/台账查询，barrier 归属在调用前已知。
- 未出现 'already held by operation' 类被拒回执，台账未因本次会话新增 barrier-conflict failed 记录（除非任务即测试该路径）。

## Counterexamples
- 在途单已终态、barrier 已释放：直接发起新操作即正确，preflight 是多余一步。
- 同步完成、受理即返回终态的系统：无在途窗口，不适用此方法。
- 任务目标本身就是验证互斥拒绝路径：被拒回执正是待采集证据，不应回避冲突。
