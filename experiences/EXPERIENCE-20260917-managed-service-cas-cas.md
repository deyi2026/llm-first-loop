---
title: managed-service 并行部署 CAS 竞争处置：读最新记录→并集合并→门禁→CAS 重试
scenario: "managed-service 双 root 部署以 managed_service_deployment.json 单记录 + 代数断言推进；并行会话活跃时，本轮预检的 generation 在本地提交/合并期间被对方推进（2026-09-17 gen8 @22:03、gen9 @22:24:57 两度发生），盲写会覆盖对方已部署线或反向回滚"
root_cause: ""
solution: 写记录前断言当前 generation；冲突时停写：检查 serving git_head 谱系，把对方 head merge 进本地线，过门禁，main 快进到并集，再以最新代数+1 CAS 重写记录并重启验收。绝不从旧 base 直接部署
evidence: "gen9/gen10 回执：22:24:57 rc=0 @28f7dc7d（对方）、22:28:58 rc=0 @d3f6b150（本轮并集）；CAS 断言两次拦截（expect gen7 got 8 / expect gen8 got 9）；并集合并 0ce51395、d3f6b150 零冲突过门禁，main=serving=d3f6b150"
tags: [managed-service, deployment, cas, parallel-operator, git-merge]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-17T22:31:30.834089+08:00"
updated_at: "2026-09-17T22:31:30.834089+08:00"
---

背景：web+feishu 双 root 进程以 data/runtime/managed_service_deployment.json 单记录（generation/git_head/code_root）为部署真值，服务重启按记录内容执行；并行会话活跃时存在写竞争。
做法：(1) 写记录前必须断言读到的 generation == 本轮预期（CAS）；断言失败=对方已推进，停写，绝不覆盖。(2) 冲突处置四步：读最新记录 git_head → `git merge-base --is-ancestor` 判谱系，把对方 head merge 进本地目标线（两轮均文件集不相交、零冲突）→ 跑门禁（verify_docs_sync + 变更相关单测）→ 以最新代数+1 重写记录再重启验证。(3) 禁止从自己旧 base 直接部署：谱系不含对方 head 时，部署即回滚对方已验证工作（gen4 教训同源）。
边界：并行会话若从旧分支部署仍会丢本地线——需用户侧协调"部署前 merge 本地 main"；git push 若被远端拒（非 FF）停止不强推。