---
title: "service_control restart 失败\"deployment binding failed: git_head mismatch\"的处置路径（operator publish 围栏）"
scenario: "managed-service（web/feishu/learning）desire 状态重启：main 合并 PR 后 service_control restart 立即失败，detail=\"deployment binding failed: git_head mismatch desired=X actual=Y\""
root_cause: ""
solution: "诊断链：① service_control(action=status, action_id=...) 带 action_id 才能看到失败详情（不带只看到 live 未变+stable 旧记录）；② mismatch 含义：published deployment gen 的 git_head ≠ code_root 当前 git rev-parse HEAD；③ 修复前置：主 worktree 必须在 main 且 tracked-clean（并行 EVO run 可能把它留在 feature 分支，publish 会绑错 HEAD）；④ publish 是 operator-only 围栏（模型直跑 publish CLI 会被\"operator control-plane only\"拦截），把 exact 命令交给用户：cd mirror && PYTHONPATH=src .venv/bin/python -m llm_loop.runtime.service_control publish --expected-generation <当前gen> --code-root <mirror> --runtime-root <mirror> --data-dir <mirror>/data；⑤ operator publish 后模型用 service_control restart expected_generation=<新gen> 重发。另：gen 推进后未重启的服务（如 web）会显示 restart_required=true，属预期漂移。"
evidence: "失败回执 action_id=svc-e9bcd5bda1a448a9bf8fd30aa5ce431a / svc-dfec7dff54014d489ee4844f13b75554（detail: deployment binding failed: git_head mismatch desired=2aadb209e... actual=de5893852...）；src/llm_loop/runtime/service_control.py L1071-1084 binding fail-closed、L1128-1155 verify、L1182-1217 build_deployment 绑 HEAD、L1228+ publish CAS；scripts/restart_mirror.sh L158-181 preflight\"operator publish\"提示；publish 调用被围栏拦截回执。"
tags: [service_control, managed-service, restart, deployment-binding, operator-fence, gen-cas]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-20T12:29:47.906440+08:00"
updated_at: "2026-09-20T12:29:47.906440+08:00"
supersedes: [EXPERIENCE-20260917-mirror-service-control-restart-qualified-worktree, EXPERIENCE-20260918-service-control-restart-fail-closed, EXPERIENCE-20260919-desired-deployment-worktree-publish-knowledge-heal]
---

2026-09-20：用户授权重启 feishu/learning（service_control restart expected_generation=53），回执 accepted 但实际毫秒级失败。status 不带 action_id 只见 live 未变，带 action_id 才见 detail。根因：gen53 desired git_head=2aadb209e，但 lfl/main 已推进到 de5893852（PR#52/#53 合并），verify_deployment_binding 用 git -C code_root rev-parse HEAD 比对，mismatch 即 fail-closed。且 code_root 当前被并行 EVO run 留在 feature 分支，publish 会绑错 HEAD——须先 git switch main。publish CLI（llm_loop.runtime.service_control publish --expected-generation N）被操作面围栏拦截（"operator control-plane only"），restart_mirror.sh 预检同样要求 operator publish。正确协作流：模型侧 git switch main 保持干净 → 请 operator 跑 publish（expected_generation=当前gen，新gen=+1）→ service_control restart 用新 generation 重发 → 带action_id查终态。另注意：wake 续跑轮不可再注册 wake（不可递归唤醒），无法自动轮询 operator 是否已 publish。