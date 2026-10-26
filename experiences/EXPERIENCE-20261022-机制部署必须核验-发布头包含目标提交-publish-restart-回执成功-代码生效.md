---
title: 机制部署必须核验「发布头包含目标提交」——publish/restart 回执成功≠代码生效
scenario: "EVO-20261022-331eee17 部署：publish+restart 回执全部 succeeded，但行为探针（review_admission 材料）仍返回旧口径 material=210866B。根因：机制提交 7ce5cd99a 只在 evo/review-host-push-material-20261022 分支、从未并入 main；19:06 publish 发布的是不含它的 main HEAD 5e05ab222，.releases/5e05ab222 快照 grep 新符号=0。"
root_cause: ""
solution: 部署前三步核验：1) git merge-base --is-ancestor <机制提交> <将发布头>，非 ancestor 先 merge --no-ff 再发布；2) 部署后行为探针验证（材料应按 push 目标收窄，仍 210866B=旧代码）；3) 会话型服务 restart 两阶段等 requester 退出才换进程——宿主未换前本会话探针恒旧口径，push 类闸门操作编排到换进程后的 wake 会话执行（sched + task_state 执行书），不在旧进程会话强推/降闸。
evidence: "本会话工具回执链：review_admission(start, git_push, runtime, d5023fa:main) 返回 material=210866B（旧行为，evidence://v1/64084f41… 的姊妹回执）；mirror 侧 grep .releases/5e05ab222…/review_host_admission.py 新符号=0；git merge-base --is-ancestor 7ce5cd99a 5e05ab222=false；修复后 merge 7a96a695a + publish gen 305（deployment_id=deploy-3e274647fb304716998482b051af0a95）+ restart 受理 svc-c7f7f88b。"
tags: [deployment, service_control, verify-before-declare, EVO, review_admission]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-22T19:45:11.939307+08:00"
updated_at: "2026-10-22T19:45:11.939307+08:00"
---

机制部署的"发布成功"≠"目标代码生效"。判定生效的最小闭环：①git merge-base --is-ancestor <机制提交> <发布头>；②行为探针（对机制改的工具/端点发已知用例比对预期，本例 material=210866B=旧、≪210866B=新）；③进程事实（.releases/<sha> 目录、ps pid 起始时间、venv editable 解析三者一致）。三者缺一即可能出现"publish succeeded + restart succeeded + 旧代码仍在跑"。