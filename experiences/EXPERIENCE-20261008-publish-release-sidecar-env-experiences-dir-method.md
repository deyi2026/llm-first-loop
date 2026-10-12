---
title: publish 后新 release 根必须补 sidecar .env（EXPERIENCES_DIR/METHODS_DIR），否则 R2 预检拒重启
scenario: llm-first-loop 生产部署：service_control publish 新 release 根后，restartMirror R2 knowledge-binding 预检失败（dual_root_store_binding_missing），restart 动作 failed（stale_receipt / stage_fact=not_started）
root_cause: ""
solution: publish 生成的新 release 根（.releases/<git_head>/）缺 sidecar .env：从上一可用 release 根复制 2 行 EXPERIENCES_DIR/METHODS_DIR 声明后重新派发 restart；failed 动作屏障由新 restart 自动接管，无需伪造 verify_acknowledge
evidence: "evidence://v1/19c1f644a3ecd98d105ae92954a106de2cc10f9c3bd7e48d04e0a9bb98bc6fe1；失败日志 data/service-control-restart-logs/svc-8a470f0fd1ac4c5eb53c328ee3df6d86.log（dual_root_store_binding_missing）与重派成功回执 feishu/learning verify=confirmed_ok gen197"
tags: [service-control, publish, restart, env-sidecar, preflight]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-08T08:10:18.973100+08:00"
updated_at: "2026-10-08T08:10:18.973100+08:00"
---

现象：publish 成功（新 desired generation）后 restart_mirror 立即 rc=1，detail=receipt=stale_receipt 或 stage_fact=not_started；日志根因为 R2 knowledge-binding 预检 reasons=["dual_root_store_binding_missing:experiences","dual_root_store_binding_missing:methods"]。机制：R2 预检要求主根与 release 根两份 .env 显式声明 EXPERIENCES_DIR/METHODS_DIR 指向 canonical store；.env 是本地未跟踪文件，publish 快照新 release 根时不携带，导致 binding source 退化 data_dir_inferred→fail-closed。处置：cp 旧 release 根的 2 行 sidecar .env 到新 release 根（RESTART-GUIDE §13 惯例），对同 target 重新派发 restart 即接管屏障并成功（failed 终态动作无需伪 verify_acknowledge accept 置成功，新 restart 可直接接管）。预防：每次 publish 后、首次 restart 前，检查新 release 根 .env 是否存在。当前性验证：grep -E '^(EXPERIENCES_DIR|METHODS_DIR)=' /Users/yyj/Project/llm-first-loop-mirror/.releases/$(python3 -c "import json;print(json.load(open('/Users/yyj/Project/llm-first-loop-mirror/data/runtime/managed_service_deployment.json'))['git_head'])")/.env 应得 2 行输出；复现：删除该 .env 后跑 CLI restart --target feishu，动作应 failed 且日志含 dual_root_store_binding_missing。