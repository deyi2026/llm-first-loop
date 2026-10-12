---
method_id: state-ledger-first-incremental-ops-d161d4f28c80
name: state-ledger-first-incremental-ops
description: 当用户请求是对既有系统的增量改进（措辞引用已有能力/工具/"这个"），先恢复环境持久状态再动手发现：goal/task 台账通常直接命名负责子系统与其 CLI 能力面，deployment/service observation 给出代码根、web 入口与当前配置。一次读记录即可收敛"哪个工具/哪个仓库/当前状态"三个未知量，取代全仓 config/内容盲搜；后续文件枚举须定根到记录指名 code_root 的规范源码树（src-layout），绕开 egg-info 旁路副本与 minified vendor 资产。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cba0dcfa-4656-4850-921d-1fad481ce73d:439:44487bc5ead14e0734cb
evidence_refs: learning:learn:20e7b6924cad
created_at: 2026-09-20T17:23:06.443948+00:00
updated_at: 2026-09-20T17:23:06.443948+00:00
---
## Trigger
用户措辞为 increment-on-existing（"完善/改进/更优雅地切换/配置这个"等指代既有系统），且环境中存在可查询的 goal/task 状态台账或 deployment/service observation 记录。

## Discriminator
请求措辞明确是改进既有机制 + 环境有廉价可查的状态记录 → 候选下一跳从"任意 config 文件/全仓内容搜索"收缩为"先读台账与 observation"；台账内容会进一步命名确切子系统（本集：runtime/lfrt 及其 switch/warmup/多后端能力面），observation 命名确切 code_root 与当前 model_ref。此判别在发起任何搜索之前即可观察到。

## Short path
- 识别增量措辞 → 先查 goal/task ledger，未知量：哪个子系统已拥有该能力（而非先做 config 内容盲搜）
- 查 deployment/service observation，未知量：线上代码根、web 入口、当前 model_ref/端口/后端状态
- 沿台账命名的 CLI 读其头部文档与 config（若不在 PATH，按台账指名的仓库路径直接调用），未知量：现有能力与用户诉求的差距（如跨后端单次重启切换、切换后自动同步注册表）
- 在 observation 指名的 code_root 内按 src-layout 定根枚举规范源码树（find src/<pkg>/web），未知量：web 端扩展点（provider 注册表/管理路由）
- 实现后经该子系统自身测试面 + 真实 CLI 冒烟 + 服务状态验证，停止发现

## Stop conditions
- 已从台账/observation 与规范源码树取得：负责子系统、代码根、当前配置、web 扩展点 → 进入实现，不再扩大发现
- 用户所需行为已由真实 CLI 冒烟与测试全绿验证（含服务终态 status 确认）

## Verification
- 最终修改落在 observation 指名 code_root 的规范源码树内（src/<pkg>/...，而非顶层 egg-info 旁路副本或 vendor 资产）
- 子系统自身单测 + 真实服务 status/smoke 通过；web 面板操作走该子系统真实输出验证

## Counterexamples
- 绿地任务：台账无相关条目，查询空手而归 → 应直接目录/搜索发现，勿强行套用本方法
- 台账严重过期（所述子系统已被替换或弃用）→ 须先以文件存在性/服务状态证实记录仍有效，否则记录反而误导
- 仓库为单一源码树、无副本无 vendor 目录 → 定根规则无增益，直接在仓内搜索即可
