---
method_id: excluded-artifact-tests-reuse-sibling-availability-gate-020629ebf0a8
name: excluded-artifact-tests-reuse-sibling-availability-gate
description: 当某测试仅在 CI/公开分发树失败、报读取'按分发约定被有意排除的内部目录'下文件缺失，而开发工作区全绿时：不要发明新跳过机制，也不要用宽文件系统枚举找本地导出树（发布树的无目录权威环境就是公开仓库的全新克隆）。判别事实是同一 CI run 中引用同一被排除目录的兄弟测试通过了——它已内嵌现成的环境可用性门（目录 is_dir() 探测 + skipif）。读先例、同构复用其门模式，并在'含目录工作区=实际执行通过'与'发布树克隆=精确 skip'双环境验证后再提交。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:1565:0c9a9a708e6fa35c1d66
evidence_refs: learning:learn:8c3e01c6c1e1
created_at: 2026-10-12T10:28:44.734225+08:00
updated_at: 2026-10-12T10:28:44.734225+08:00
---
## Trigger
测试在开发工作区通过、但在 CI/公开分发环境失败，错误为 FileNotFoundError，且缺失路径位于分发约定明确不分发的内部目录（治理/specs/私有文档类）；即失败由'环境缺目录'而非代码缺陷导致。

## Discriminator
同一 run 的对照事实（当时已可见）：pytest 步骤报告 8239 passed 且唯一失败是指向被排除目录的测试——这意味着引用同一被排除目录的其他测试在该 run 中全部通过，证明仓库已存在正确处理'目录缺失'的先例门模式，且目录缺失是分发约定而非事故。grep 全库引用该目录的文件可一步定位先例。

## Short path
- 从 CI 日志提取唯一失败测试名与其读取的缺失路径（先读 traceback，不猜测根因）
- 读失败测试头部：确认依赖的 `_DIR/path` 常量与是否已有可用性门
- grep 全库引用该被排除目录的测试文件；结合'唯一失败'事实，通过者即现成先例
- 读先例的门写法（探测标志 + skipif + import），同构应用到失败测试，不新造机制
- 双环境验证：原工作区该测试实际执行并通过；克隆公开发布树（天然无该目录）后应精确 skip 该测试、其余通过
- 提交双侧、看新 CI run 全绿即停止；不做额外探索

## Stop conditions
- 已确认先例测试在同一 run 中通过，且其门模式直接覆盖失败测试的缺失路径（修复方案锁定）
- 双环境行为符合预期：含目录环境执行通过、无目录发布树克隆中精确 skip
- 新 CI run 门禁与安全扫描全绿

## Verification
- 含目录的原工作区跑该测试文件：目标测试实际执行（结果为 passed 而非 skipped）且全绿
- 在无目录的发布树克隆中用同一 venv 跑该测试文件：skip 计数恰为被修复的那一个测试，其余通过
- 新 CI run 的失败步骤由 X 变为 ✓，且 skipped 项（如 nightly）按条件跳过而非失败

## Counterexamples
- 缺失文件并非按约定排除（错误合并、应分发文件被误删）：正确修复是恢复文件，加 skipif 会掩盖真实回归
- 该测试的存在意义就是强制该 artifact 存在（presence/契约类主对象）：不能 skip，应改 artifact 落点或用环境 fixture 重构，而非环境门
- 本地/CI 差异与'有意排除'无关（依赖版本偏差、flaky、网络）：必须先证伪分发约定假设，再考虑门模式
- 兄弟测试只是碰巧通过（参数化跳过、该分支未触发）：未读其代码确认门真实处理缺失前，不得直接复用其模式
