---
title: "sandbox 下 vitest 报一堆 mkdir EPERM / \"no tests\"：改 TMPDIR + --no-cache"
scenario: "macOS sandbox-exec（仅允许写工作区/缓存目录）里跑 webui 的 vitest 全量：出现数十条 unhandled error \"EPERM: operation not permitted, mkdir '/var/folders/.../T/...'\" 与 node_modules/.vite 写入失败，汇总为 \"no tests\"，容易被误判成代码或测试缺陷。"
root_cause: sandbox 只允许写工作区与缓存目录：$TMPDIR 在 /var/folders、node_modules 为主仓软链，二者写入均被拒；vitest 的临时文件与结果缓存默认落在这些位置。
solution: |
  根因是 $TMPDIR（/var/folders）与 worktree 里 node_modules 软链指向的主仓路径都不可写。做法：在 webui 目录内建 .tmp-vitest/tmp，命令改为 TMPDIR="$PWD/.tmp-vitest/tmp" npx vitest run --no-cache；vitest 2.1.9 的 --cache.dir 已弃用，--no-cache 可避免写 node_modules/.vite。跑完删除 .tmp-vitest，避免给候选工作树新增未跟踪文件（会影响 review_admission 冻结材料）。
  当前性验证：cd webui && npx vitest --help | grep -- "--no-cache" 应命中；随后 TMPDIR="$PWD/.tmp-vitest/tmp" npx vitest run --no-cache 应输出 "Test Files N passed" 且 exit 0（若仍出现 /var/folders mkdir EPERM，说明 TMPDIR 未生效或被覆盖）。
evidence: "webui vitest：Test Files 56 passed (56) / Tests 553 passed (553)，exit 0（job job-2f9a5bbbc3d849608218, evidence://v1/622bb48e3e97ef513ed37813e2cc39710c2855fa17903963e01be1ea1c7fa2a6）；对照失败轮 job-66ba38390b644321a153（56 unhandled mkdir EPERM / no tests）。"
tags: [vitest, sandbox, TMPDIR, webui, 测试环境]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-27T16:29:30.060745+08:00"
updated_at: "2026-10-27T16:29:30.060745+08:00"
---