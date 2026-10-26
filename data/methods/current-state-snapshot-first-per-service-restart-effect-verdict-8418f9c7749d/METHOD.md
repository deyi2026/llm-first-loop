---
method_id: current-state-snapshot-first-per-service-restart-effect-verdict-8418f9c7749d
name: current-state-snapshot-first-per-service-restart-effect-verdict
description: 多受管服务重启或发布是否生效，第一跳读取与目标服务绑定的权威 desired/live/stable 快照；以 live PID 存活和 live.git_head==desired.git_head 判断当前运行版本，stable.generation 是上一次成功动作的历史回执，不以本机 checkout HEAD 或旧 stable 代次替代 desired。配置与功能是否生效另用真实入口探针，accepted 不等于 succeeded。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:826dee73-c003-4696-bfb3-c443dcac35b9:1853:abbe38d30e76c85b3860
evidence_refs: learning:learn:6c2c9d151bb2
created_at: 2026-10-22T21:04:50.417719+08:00
updated_at: 2026-10-26T06:56:06+08:00
---
## Trigger
用户询问一次已执行的重启/发布是否'生效'，且平台存在按目标记录 PID、started_at、git_head、code_current 的权威状态/版本快照工具

## Discriminator
先区别三种身份：desired 是当前发布目标 SHA/代次；live 是各服务 PID_alive、真实启动代码 SHA；stable 是最后一次成功重启动作的代次和时间。工作区 HEAD 可能已提交更远版本，不是服务应当运行的 desired。只有 stable 当前代时才可声明其 Git 身份；stable 旧代的 SHA 应标未知。

## Short path
- 先明确用户问的是 Web/Feishu/Learning 哪些服务；只读读取当前 `service_control` desired、live、stable、restart_required 与在途 action，严禁复用上一轮旧快照。
- 逐服务判断：live PID 有效且 live.git_head==desired.git_head、restart_required=false → **运行代码与目标一致**；live 不一致/已死 → **尚未生效**；缺身份字段 → **未证实**，转查该服务 manifest 与精确 action。
- stable.generation 不等于 desired 时只报告**历史成功回执滞后**，绝不据此推断运行了旧 SHA，更不能仅为追平数字而重启。
- 如果问的是登录、语音、WebUI 是否可用，另核对对应真实接口与前端资源（例如 `/auth/status` 与 `/ui/v2/`）；HTTP 200 或旧浏览器页本身不能证明候选全部上线。
- 将“代码运行身份 / 稳定回执 / 实际功能 / 其他待办（GitHub push 等）”分别报告；事实够用即停，不扩散到无关进程。

## Stop conditions
- 每个重启目标都拿到快照字段或动作回执背书的生效/未生效裁决
- 未收口项已用各自独立权威来源（如 git log origin/main..HEAD、evolution_exec 记录）核实并单独列出
- 不再对与裁决无关的进程、实验目录做补充枚举或继续宽探测

## Verification
- 针对每个目标保留 desired SHA+generation、live PID+SHA、stable generation+action 时间，核对是否绑定同一时刻快照。
- succeeded/confirmed_ok 是受管动作终态；accepted/waiting_for_requester_exit 不是成功；如有真实失败，保留精确 action_id 和日志。
- 对于只有 stable 回执落后的情况，不用“全部版本不一致”误判；对于 live 实际落后 desired 的情况，不能用历史成功回执掩盖。
- 使用 `2026-10-26` Gen 323 Web 单服务成功案例和 Gen 319 stable315 但 live 匹配反例作为检验样例。

## Counterexamples
- 未受管裸进程没有 desired/live/stable 控制面，改以进程和真实端口为证。
- 用户问的是具体配置、语音/前端功能是否激活，运行 SHA 只证明身份，必须追加最小真实功能探针。
- 新会话中“重启”目标 genuinely 未知，可做一次有界历史检索消解指代。
- 在途 publish 已改变 desired：旧快照失效，需重新读取；不要假设当前 checkout HEAD 就是 desired HEAD。
- 单服务问题结果一行可回答时不硬堆三分区。
