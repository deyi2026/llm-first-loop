---
method_id: probe-executor-code-version-then-invoke-production-function-8b3650410be7
name: probe-executor-code-version-then-invoke-production-function
description: 当被修改的代码正是执行该修改的运行中系统自身加载的版本（self-hosting 发布链：publish 由运行中旧代服务执行，venv 经 .pth 绑定旧 release）时，改动不会自动作用于当前代。先用 import 探针确认执行器实际解析的代码路径；若仍绑定旧代码，不要用手写工件补丁，而是以显式路径覆盖（如 PYTHONPATH=新 src）直接调用生产函数的幂等复用/修复路径，由生产函数自身完成当前代物化，再用真实 gate 做前后对照。并明确该自举缺口只存在于切换代，之后各代自然继承。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ae8c5d92-6fe9-45af-bd9c-ef4912bb21e4:964:961b8f1e894cf3910bf4
evidence_refs: learning:learn:47b95b4c6d81
created_at: 2026-10-08T08:47:09.546518+08:00
updated_at: 2026-10-08T08:47:09.546518+08:00
---
## Trigger
一次代码修复需要由当前运行中的旧版本系统自身执行才能作用到当前代（发布链自举、插件/工具自更新、venv .pth 绑定旧 release），而默认执行器加载的仍是修改前代码。

## Discriminator
当时即可测的执行器绑定事实：import 探针显示 .venv 的 llm_loop 经 .pth 解析到旧 release 路径，且 publish 由运行中旧代服务执行；同时被改的生产函数存在幂等的复用/修复路径，可安全直接调用。

## Short path
- 实现修复并通过单测（先证新代码自身正确）
- 提出明确未知量：本次物化由哪个版本的代码执行？用 import 探针打印执行器实际解析的模块路径
- 探针显示绑定旧代码 → 不手写工件，用显式路径覆盖调用生产函数的复用/修复路径完成当前代物化
- 用真实 preflight/gate 做前后对照（缺键 fail → ok/exit=0）验证生产函数产物
- 确认缺口仅存在于切换代后收口，下一代替发布自然继承修复

## Stop conditions
- 生产函数自身报告成功且真实 preflight 无需人工补文件即 PASS
- 执行器探针显示已解析到新代码（无自举缺口）→ 按常规发布流程即可

## Verification
- 物化产物由生产函数生成而非手写（过程日志/commit 可审计）
- 真实 gate 前后对照：修复前 dual_root_store_binding_missing/exit=2，物化后 ok:true/exit=0
- 端到端测试断言新 publish 的 release 不经人工补丁即通过 preflight

## Counterexamples
- 修改只由全新进程执行（单元测试、新起 CLI），执行器不缓存旧代码 → 无需自举处理
- 目标生产函数非幂等或有不可逆副作用，直接调用风险大于收益 → 先在隔离环境验证
- 变更对象是纯数据/配置，不存在代码版本绑定问题
- 执行器与被改代码完全解耦（远端服务、独立进程），新代码下次启动自然生效
