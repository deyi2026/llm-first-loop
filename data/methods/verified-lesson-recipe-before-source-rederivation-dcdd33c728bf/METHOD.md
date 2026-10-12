---
method_id: verified-lesson-recipe-before-source-rederivation-dcdd33c728bf
name: verified-lesson-recipe-before-source-rederivation
description: 当检索命中一条 status=active、带证据引用的历史经验/教训，且其 solution 已给出本次受门禁变更（publish/restart 类）的完整配方——步骤、前置条件、权限边界——时，把它当作主计划执行：只用只读命令核对其点名的前置条件（目标 commit、tracked 干净、构件新鲜度），逐项最小化解除阻塞，把权限外的步骤按配方交给操作员。不要重新从实现源码推导权限围栏与控制面架构，除非某项前置检查与经验相矛盾，或经验的代际早于现行代码重构。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6e0fb83b-03af-44ff-be33-c3498380b42f:1098:9c544546656e6be2ea5e
evidence_refs: learning:learn:c0eeb11b86f0
created_at: 2026-09-20T21:07:38.260412+00:00
updated_at: 2026-09-20T21:07:38.260412+00:00
---
## Trigger
任务是对受门禁的系统状态做受控变更（如部署 publish+restart），且已命中一条 active、含具体证据引用的经验，其 solution 明确写出本次操作的执行步骤、前置条件与执行权限边界；同时首轮状态查询显示该变更尚未生效（如 live==stable、restart_required=false），缺失的恰是经验所覆盖的那一步。

## Discriminator
扩散发生前已读到的经验正文同时包含：(a) 精确执行配方（从哪个 root 发起、expected-generation 语义、verify 通过后仅执行一次后续动作）；(b) 权限边界声明（受门禁子命令为 operator-only，模型会话不可自行变更 desired 状态）。加上首轮状态查询已给出 live 与 desired 的差距。这两类当时已存在的事实足以把'源码考古+围栏接线考证+侧产物调查'收缩为'核对配方点名的少数前置条件并逐项解除'。

## Short path
- 读当前 live/desired 状态：未知量=哪个受门禁步骤缺失（generation、live head、restart 标志）。
- 检索并读取命中的 active 经验：未知量=已验证的安全配方与权限边界；直接从 solution 文本提取步骤、前置条件、谁可执行。
- 只核对配方点名的前置条件：HEAD 是否等于目标 commit、tracked 工作区是否干净、部署构件自 live head 以来是否有源变更——全部只读命令。
- 对每项失败前置做最小处置：stash 与本任务无关的未提交改动、提交积压资产使 tracked 干净；忽略不阻塞检查的状态（如 untracked 目录，当前置检查显式排除 untracked 时）。
- 把精确的门禁命令（含正确的 expected-generation）连同事后验证清单交给操作员；操作员确认后经模型许可路径执行后续 restart，并按经验判据验证生效。

## Stop conditions
- 配方全部前置条件通过，且门禁命令已按权限边界交付操作员（或在权限内执行完毕）。
- 按经验完成事后验证：generation 如预期推进、目标服务运行在目标 head、经验点名的生效标志成立。
- 任一前置检查结果与经验相矛盾，或经验代际早于现行控制面重构：停止套用配方，转入源码级核证分支。

## Verification
- 变更后核对 desired generation 按语义推进（expected-generation 一致）且服务 git_head 等于目标 commit。
- 验证经验的生效判据本身（如模型会话再次探测受门禁子命令被拦截、目标门控在无残留时判 idle）。
- 确认部署谱系未混入无关产物：stash 可恢复、非阻塞 untracked 项未被误提交。

## Counterexamples
- 经验成文于控制面重构之前（门禁/CLI 面已改名或变更）：其权限与流程断言必须重新在源码验证，本方法不适用。
- 没有命中任何 active 且带证据引用的经验：此时 docs/源码层面的发现才是正确路径。
- 前置检查出现经验未覆盖的新失败模式（如门禁新增了构件重建要求）：应退回读取执行代码的检查逻辑，而非继续按配方推断。
- 经验的故障模式与当前风险不同类（如它讲来源分歧而当前风险是凭据/安全钩子）：只移植直接对应的步骤，不得整卡照搬。
