---
title: 准入容量门跑在服务进程内存模块上：判“新码已生效”看 hosting 进程启动时 git_head，不看仓库 HEAD/发布目录
scenario: "修复提交 62939c22a 已合入工作树并发布（发布目录 .releases/62939c22a… 的 review_host_admission.py 已含 _is_vendored_asset，vendored 资产取件上限放宽到 8_000_000B），但承载本会话的 feishu 服务进程自 2026-10-31T10:56:05 起一直运行 b008c9fae 的旧模块；同参数 review_admission(action=start) 仍回 accepted=false, reason='git_state_too_large:material_diff>400000'（无 child_id、无 qualification）。"
root_cause: 旧进程内存模块缺 _is_vendored_asset 分支，vendored 资产 diff 走 400000B 严格单路径上限而超限；新码下该类走 8MB 取件 + 48KB 投影路径。
solution: "重跑准入前先确认 hosting 进程已载入新码：读 architecture_status(dimensions=['process_versions'], scope='runtime') 的 per-service git_head 与 service_control(status).services.<svc>.live.git_head；进程 git_head≠desired_git_head 即为旧码，须等该服务收敛后再重跑，不靠‘仓库有该提交/发布目录有该文件’推断。"
evidence: "本 run 回执：review_admission → {\"accepted\": false, \"reason\": \"git_state_too_large:material_diff>400000\"}；process_versions：feishu pid=80361 started_at=2026-10-31T10:56:05 git_head=b008c9fae（web pid=82484 已为 62939c22a）；.releases/62939c22a…/src/llm_loop/tools/review_host_admission.py 中 _is_vendored_asset 命中 4 处、_VENDORED_ASSET_DIFF_ACQUIRE_MAX_BYTES=8_000_000；/tmp/lfl-integrate rev-parse HEAD=62939c22a46498d4c3ebe09b424150800c33ecdf 且工作树干净。"
tags: [review_admission, service_control, 部署收敛, 进程内存模块, git_state_too_large]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T22:04:43.359991+08:00"
updated_at: "2026-10-31T22:04:43.359991+08:00"
---