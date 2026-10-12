---
title: mirror 纯重启（同码）service_control 操作契约：精确代次、异步回执链与通道死亡恢复
scenario: "llm-first-loop-mirror 常驻 web(:8903)/feishu 需要同码重启（.env/配置重载、崩溃恢复、guard 提示需重启生效），或需要验证 service_control 重启终态。service_control(action=restart) 按 data/runtime/managed_service_deployment.json 的 code_root 复活：只换 PID 不换代码。2026-09-17 双向实证：gen3 同码重启后进程 git_head 仍 3eaae8f6（新代码未生效）；推进记录到 gen4 后才载入 54441fd4。"
root_cause: "service_control 重启是 desired-state 记录绑定 + 异步 detached worker + 执行通道与被重启服务共享宿主，三者叠加使\"重启\"在工具层表现为非同步、非自证的操作：回执 accepted 只是受理，代码按记录而非按工作区加载，通道可能在窗口内死亡。"
solution: 按 body 的 7 步契约执行：status 取精确代次 → 空闲预检 → 发起后轮询 action JSON 至终态（勿重复发起）→ 通道报 unknown_after_restart 则等待重查 → 五件套验收（动作记录/回执 SHA/新 PID/入口三连/心跳+8901）→ 严格区分纯重启与上码两条路径 → 直跑脚本换码后必须回写 managed 记录。
evidence: 2026-09-17 会话回执可独立核查：action svc-f112e86e33b64dcb9aa4d37f929469b9（gen3 同码，restart_mirror rc=0，新 PID 65411/65510 仍 @3eaae8f6）；action svc-d695fc15db0f405898dcf90b04afc9d0（gen4，rc=0）；data/restart-receipt.json git_head_full=54441fd41a8f2ee0008d1fedc037a89e1240d1fa、web_pid=33716、feishu_pid=33858；proc_versions 双服务 @54441fd4 workspace_dirty=false；入口 auth/status=200、ui/v2=303、login=200；心跳 pid=33858 connected。
tags: [mirror, restart, service_control, managed-deployment, ops, verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-17T20:22:47.868327+08:00"
updated_at: "2026-09-17T20:22:47.868327+08:00"
---

mirror 纯重启（同码）操作契约（service_control 时代，2026-09-17 实证）：
1. 先 status 取当前 generation；expected_generation 必须精确等于它（防并发操作者/旧信息误触发）。
2. 空闲预检：feishu_heartbeat.json 的 processing_msg_id=="" 且 queue_depth==0；web 无在途任务（指南 §4.4）。
3. accepted ≠ 完成：异步 detached worker，轮询 data/runtime/service-control-actions/<action_id>.json 至终态 + data/restart-receipt.json rc=0；勿重复发起。
4. 执行通道在重启窗口内死亡（execute_command 报 unknown_after_restart）属预期：等待后重查事实，不重跑命令。
5. 验收最小集（rc=0/端口监听不算数）：动作记录 succeeded；回执 git_head_full=记录 SHA；新 PID 存活且 @目标 SHA（proc_versions）；/auth/status=200 + /ui/v2/ 未登录 303 + /login=200；feishu 心跳 connected 且 pid=新 PID；8901 未动。
6. 用途边界：纯重启只适用 env/.env 重载与崩溃恢复；上代码必须走 qualified worktree + 记录推进（方法卡 method:lfl-mirror-qualified-worktree-33ba78f2f2e7 的 S0-S8）。
7. 危险边角：若有人绕过记录直跑 restart_mirror.sh 换了 code root，下次 service_control restart 会按 managed_service_deployment.json 旧记录复活旧代码——直跑后必须同步记录。