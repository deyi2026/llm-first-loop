---
method_id: deterministic-guard-preflight-before-expensive-review-gate-04158fca7d66
name: deterministic-guard-preflight-before-expensive-review-gate
description: 语义审查对『定义在审查切片之外』的确定性守卫零信息量：本集 GLM-5.3 对 service_control.py::main 实测568>登记562、installation<->service_control<->wheel_identity 新增 import 环仍给 PASS，而守卫测试 35 秒确定性红。冻结候选进入昂贵门禁（约25分钟异步审查+全量CI）前，先只读跑仓库守卫套件；守卫红则修复必改候选 SHA、该轮审查注定作废，应在 review start 前止损，避免『审查PASS→门禁红→修复→换SHA二轮重审』。
aliases: 送审前先跑守卫测试, 审查过了CI挂了, 函数行数棘轮超标提前查, 循环依赖门禁预跑, 冻结送审前架构守卫预检
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:3b90bb3d-7904-45a5-824a-e1efe5e27028:0:1cfe12f782f8b659ef2c
evidence_refs: learning:learn:627f41f9579d
created_at: 2026-11-08T20:43:05.957697+08:00
updated_at: 2026-11-08T20:43:05.957697+08:00
---
## Trigger
候选补丁即将冻结送昂贵资格门禁（异步独立审查/全量CI/发布构建），且补丁修改受棘轮管辖的源文件（函数行数基线、全局红线）或在有 import 环禁令的包内新增跨模块 import，而守卫测试与基线台账不在审查切片的声明路径内

## Discriminator
冻结前从 git diff --cached 路径清单即可读出：补丁既含棘轮管辖文件的修改、又新增会相互/反向 import 的模块，同时守卫测试与冻结台账不在声明路径中 ⇒ 语义审查无论 PASS/REVISE 都无法裁决基线合规（Reviewer 看不到登记值 562），唯一廉价真值源是本地跑守卫套件（秒~分钟级 vs 约25分钟审查）

## Short path
- 核对身份/漂移后、review_admission(start) 前：在同一工作树只读跑守卫套件（如 pytest tests/unit/test_arch_guards.py），未知量=候选是否违反任何全库确定性不变量
- 守卫红：门禁执行者只报告并停止、不启动审查；候选作者按守卫自带合规出口修复（基线重登记前缀提交/断环或走 exemptions）——修复必改候选 SHA，当前 SHA 的审查注定作废
- 守卫绿：按序 start 独立审查；按 waiting_protocol 用 wait(≤120) 配速、status 回执是唯一完成信号，repeat_guard 触发时先记 task_state 账本再续轮询
- 仅真实 terminal completed+qualification PASS 才在同一 Host 消费一次性资格跑原版门禁；对终态如实报告，失败不重跑、不改基线、不修守卫测试

## Stop conditions
- 守卫套件红：停止，不 start 昂贵审查（候选 SHA 必须变更，送审即白烧预算）
- 守卫绿且独立审查 completed+PASS：消费资格跑原版门禁并报告真实 exit code
- 审查 REVISE/UNAVAILABLE：只报告真实结果，不跑后续门禁

## Verification
- 守卫失败自带确定性判据并应本地复现：棘轮输出登记值vs实测值（562→568）、红线阈值、环的具体模块链；同套件重跑结果不变
- 对照回执：语义审查 PASS 与守卫红并存即方法有效性的直接证据（本集 Reviewer qualification=PASS 而 R9 tier0 3 failed/338 passed）
- 修复出口必须来自守卫测试自带指引（如 regen_function_size_baseline.py 前缀提交），不得以放宽阈值或修改守卫测试代替

## Counterexamples
- 仓库无棘轮/基线守卫机制，合规完全由补丁自带且在审查切片内的测试决定：预检冗余，直接送审
- 守卫套件本身需昂贵环境（真实 systemd cgroup worker、隔离 HOME 全量构建）才能运行：守卫不再廉价，按仓库既有阶段顺序执行
- 任务目的就是测量候选对守卫的符合度（评估而非资格过滤）：门禁必须跑，预检结果是交付数据不是过滤器
- 补丁不触碰任何棘轮管辖文件、也不新增跨模块 import：跳过预检直接按规定流程执行
