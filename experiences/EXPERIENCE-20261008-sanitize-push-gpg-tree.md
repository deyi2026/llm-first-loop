---
title: sanitize-push 净化推送脚本三重障碍修复：GPG 剥离致非快进 / 广谱检查误报已公开内容 / --tree 安检前置抓真泄露
scenario: 发布净化脚本（filter-repo 剔除内部治理文档后推送公开远端）首跑在中途自检处中止，需在不放宽安全语义的前提下定位并修复脚本缺陷
root_cause: ""
solution: 区间过滤保快进 + 白名单带远端已公开证据 + 推送前本地跑远端口径 --tree 安检 + 后台门禁命令净化环境并显式落档退出码
evidence: "/tmp/r9_commit_v0627_retry.log（净化环境重跑：机检+门禁+提交三步全绿，0b7792c58）；/tmp/sanitize_push_v0627.log（首跑 FAIL：middleware 误报）；.backup/lfl-prepush-20261008.git/filter-repo/commit-map（GPG 剥离实证）；/tmp/sanitize_push_final.log（终跑：快进 2ff8efb0b..459936b99 + tags + 远端核对 exit=0）；gh release view v0.6.27（published, target 459936b99）"
tags: [sanitize-push, filter-repo, gpg-signature, fast-forward, security-scan, release]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-08T16:10:34.880792+08:00"
updated_at: "2026-10-08T16:10:34.880792+08:00"
---

v0.6.27 净化推送首跑失败三连，逐一取证修复后成功（远端 main 2ff8efb0b→459936b99 快进落地）：
1. filter-repo --refs refs/heads/main 全量区间会剥离已发布提交的 GPG 签名（commit-map 实证 e4a9c677e→5311a2fb5 仅 gpgsig 消失、tree 相同），远端 tip 及其祖先全部改哈希 → 脚本自带的"快进推送"检查必然 FAIL。修复：剔除路径若全部晚于远端 tip（git log <remote-tip> -- <paths> 零触及即证），用 --refs <remote-tip>..main 区间过滤——只重写从未发布的提交，公开结果等价（被剔除文件在任何待推历史都不出现），已发布史（含签名）原样保留。
2. 广谱字符串检查（-i 'middleware' docs）会误报已在远端公开的通用框架术语（Django MiddlewareNotUsed / WebAuth-Origin middleware）。判定标准：git grep 同字样是否存在于远端 tip 树内——在则属"拒绝与已发布状态一致的内容"，为检查 bug，白名单须带该证据登记；精确 token 检查不动。
3. 推送前必须在本地跑远端口径安检（bash scripts/git_security_scan.sh --tree，与 ci.yml security-scan 同命令）：本次抓到两处真实泄露——误跟踪的测试运行日志 .arts/unit_full_r2_20261006.log（.log$ 规则，含本机绝对路径）与 scripts/cloudflared-launch.sh 硬编码 /Users 路径。处置：tip 树内修复（git rm/改路径推导，各过一轮 r9 门禁）+ 日志同时加入 filter 剔除清单，保持"公开树=本地树"一致性。
4. 后台委派 r9_commit 时必须 env -u PYTHONPATH -u LFL_RUNTIME_ROOT 启动（复用 EXPERIENCE-20260919-worktree-ambient-env：泄漏环境使 PROBE 态 enforce_identity 假红 + 全量套件多耗 15 分钟超时等待；净化后同套件 5 分钟全绿）。另注意 `bash script.sh | tail -25` 管道会掩盖脚本退出码（registry 报 exit=0 但实际门禁红中止）——委派命令一律 `> log 2>&1; echo exit=$?` 落档。