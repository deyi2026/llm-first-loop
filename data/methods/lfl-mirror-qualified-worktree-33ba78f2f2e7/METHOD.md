---
method_id: lfl-mirror-qualified-worktree-33ba78f2f2e7
name: LFL mirror 新代码上线：qualified worktree + 代次推进全流程
description: 把"给 mirror 常驻服务上新代码"从触发到验收的完整可复用序列：血统资格检查（防回滚）→ 独立 merge worktree → 冲突骨架移植 → dist 复用/构建 → 记录推进代次 → service_control 按记录执行 → §6 全项验收 → 回滚留底。
status: hold
source_model: glm/glm-5.3
source_episode_refs: episode:010fcc8e-3ba8-4948-9ae5-66a30cc8ea6e:609:d5332e08b75dbdbd3962
freshness_refs: docs/LFL-restart-guide.md,src/llm_loop/runtime/service_control.py,scripts/restart_mirror.sh
created_at: 2026-09-17T12:15:54.265253+00:00
updated_at: 2026-09-18T14:32:25.334573+00:00
---
# LFL mirror 常驻服务新代码上线（qualified worktree + 代次推进）

适用：llm-first-loop-mirror 的 web(:8903)/feishu 需加载新提交；约束：不碰 8901、可回滚、按 docs/LFL-restart-guide.md 语义。
不适用：仅同码重启（直接 service_control restart——它按 managed_service_deployment.json 复活既有 code_root，永远不拉新码）。

S0 意图分叉：同码重启 vs 新码上线；新码上线走 S1-S8。
S1 目标资格：取 full 40 位 SHA；双向血统检查——`git log --oneline HEAD..main`（反向：分支缺运行线几个提交）+ `git diff --numstat main..HEAD | sort -k2 -rn | head` 扫"0 增/大删"（回滚信号：分支落后会表现为成片 0-additions 大 deletions）。落后→S2；否则跳 S3。
S2 补齐落后：`git worktree add --detach .worktrees/deploy-merge-<tag>-<date> <branch-tip>`，在该 worktree 内 `git merge <运行线SHA>`。冲突解法：骨架整体取运行线（checkout --theirs）+ 用 `git diff <fork-base>..<tip> -- <file>` 提取己方净增量、按运行线新风格（如 env_values/env_int）移植回。导入烟测（dummy LLM_API_KEY）+ 两侧定向测试（己方改动面套件 + 运行线改动面套件）全绿才继续。禁止在正服务 code root 或主检出脏树 checkout/merge。
S3 前端产物：`git rev-parse <target>:webui` 与运行线 webui tree 相同 → 机械复用运行中 dist（copytree + 前后文件数/树哈希断言相等 + index.html 引用资产存在）；不同 → 目标 worktree 内 npm ci && npm run build。
S4 空闲预检：data/feishu_heartbeat.json 的 processing_msg_id=="" 且 queue_depth==0；web 无在途生成任务。
S5 推进代次：先审计快照（restart-receipt/manifests/managed_service_deployment.json/pgrep/lsof:8901 → data/restart-audit/<ts>-$$）；改写 managed_service_deployment.json：generation+1、新 deployment_id=deploy-<uuid4hex>、git_head=目标 full SHA、code_root=新 worktree、dist 未变则沿用 webui_artifact_sha256（临时文件+rename 原子写）。
S6 执行：service_control restart expected_generation=<新代次> target=web|feishu|all。异步 worker：轮询 status 与 data/runtime/service-control-actions/<action_id>.json 至终态，勿重复发起；执行通道可能报 unknown_after_restart——等待后重查，不重跑。
S7 验收（全过才算成，rc=0/端口监听不算数）：动作记录 status=succeeded；新 PID@目标 SHA（runtime_manifest/proc_versions）、workspace_dirty=false、llm_loop_module 路径=新 worktree；/auth/status=200 + /ui/v2/ 未登录 303→login + /login=200；feishu 心跳 connected 且 pid=新 PID；8901 PID 未变；目标 worktree 仍 clean。
S8 回滚留底：旧 deploy worktree 原样保留不清理；合并提交挂分支/tag 防 gc；回滚=S5 改回旧记录（gen/SHA/code_root）+ service_control restart(expected_generation=旧gen)。

关键反例教训（本方法存在的原因）：(a) 只 service_control restart → 同码复活，新提交不生效；(b) 直接部署分支 tip 而不做 S1 反向检查 → 回滚运行线 43 提交/1.2 万行的量级事故。
