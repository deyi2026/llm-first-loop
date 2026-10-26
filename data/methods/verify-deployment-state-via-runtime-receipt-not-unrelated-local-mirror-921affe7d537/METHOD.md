---
method_id: verify-deployment-state-via-runtime-receipt-not-unrelated-local-mirror-921affe7d537
name: verify-deployment-state-via-runtime-receipt-not-unrelated-local-mirror
description: 部署事实核验优先使用运行服务自身的 desired/live 身份与精确 action 终态，不把 stable 旧代当成实时 Git 版本；只有当追查本地修改时才核验 checkout 与运行源码的 git-common-dir/commit lineage。单个 HTTP 200、current HEAD、accepted 都不足以证明新版本生效。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1e362f1c-6242-47df-8cfd-2b1de1b0b20e:18:c20454aa750a4e095891
evidence_refs: learning:learn:48d1e6dced4b
created_at: 2026-10-13T21:33:40.339963+08:00
updated_at: 2026-10-26T06:56:06+08:00
---
## Trigger
需要核验关于已部署服务的状态声明（已重启/代码已收口干净），且工具回执报记忆中的 workdir 无效、或本机存在多个可能不同源的 checkout

## Discriminator
先问回执是不是**当前**服务/当前 desired 的运行身份：live SHA+PID 与 desired SHA 直接裁决代码身份；stable 是历史成功动作，只有与当前 desired 对应时才可声明 Git 身份。检索仓库、git_dirty、当前 checkout HEAD 不能替代 live。若涉及多工作树发布，须确认 code_root 的 `git-common-dir` 与正式运行根同源。

## Short path
- 首先取 `service_control show/status`：desired SHA/代次、每服务 live PID/SHA 与 stable 回执、restart_required、action 终态；缺失的字段用对应 manifest 定向补齐。
- **运行已生效**应依据 live SHA == desired SHA、PID 活着、精确 action=succeeded/confirmed_ok（若讨论该次重启）；stable 旧代只报代差、不猜旧 SHA、不以它单独触发重启。
- Web 还需用户入口 `/ui/v2/`、鉴权 `/auth/status` 等探针；“200 但挂载旧资源”不能宣称 UI 修复上线。
- 如需判断源码/worktree 是否干净，再在实际 code_root 或 cwd 读取 `git status`；不同源先 `git rev-parse --path-format=absolute --git-common-dir` 并比对 commit/ancestry，不枚举全 home。
- fetch/pull 必须保留错误信息；把**服务状态**与**本地残留**分别报告，不为无关目录里的未跟踪文件阻断受管服务判读。

## Stop conditions
- 每个服务的当前 desired/live/stable 已分别核验，不把 historical receipt 误称当前代码。
- 已核实对应 action 是真实终态，或报告 pending/failed 而非强行成功。
- 本地代码/产物差异只在证实同源时影响当前部署声明，达到声明所需证据即停止。

## Verification
- Web Gen 323 发行 SHA=`2cf3ada5e…`、action `svc-2fee46dc41e04067b8a1c29dc807c753` 的 succeeded 与 live SHA/HTTP 一致；Feishu/Learning 仍运行先前 SHA，不错误宣称全部服务升级。
- 若 stable.generation < desired.generation，要以 live SHA 而非 stable 代次判断实际版本，并明确 stable 的历史性。
- 检查发布根的 Git common-dir、不可变 release SHA、WebUI dist/source binding；只有被请求时才检查本地 checkout 和 remote ancestry。

## Counterexamples
- 用户只问本地 worktree 提交/修改：本地 Git 状态才是主证据，服务 manifest 无关。
- 运行 manifest 无可信 SHA 或 action 缺终态：回到实际部署代码根/日志与健康检查，不凭空推断。
- 唯一 checkout 且 remote 确定、问题不涉部署根身份：额外 lineage 检查无益。
- 只有 stable 旧代的回执不等于服务运行旧代码；只有 HTTP 200 也不等于 WebUI 新版本生效。
