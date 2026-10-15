# RESULT 2026-10-16 — 子 Agent 生命周期与取消传播专项修复（隔离候选）

> 状态：**局部修复已实现、定向验证 PASS；独立代码 Reviewer / 原版完整 R9 未运行、未获合并及部署资格**。
>
> 评估基线：main `f7c0812825807d6dec2a2ad6e835899766229c40`。
> 隔离分支：`fix/subagent-lifecycle-audit-20261016`；工作树：`.worktrees/subagent-lifecycle-audit-20261016`。
> 本轮只改隔离工作树；没有修改本地 main、其它 Agent 工作树、生产服务或 Provider 配置。

## 1. 核查范围与证据

- 子 Agent 执行和本地状态：`src/llm_loop/subagent/runner.py`（`cancel_parent`、`_finalize_child`、`start`、`result_current`）。
- 终态展示：`src/llm_loop/tools/builtin/subagent_result.py`。
- 持久化与归属：`src/llm_loop/core/subagent_{topology,delivery}.py`。
- 资源/租约：`src/llm_loop/fleet/{coordinator,store}.py`。
- 覆盖：子 Agent、异步主子协作、重启回放、Fleet 租约、代际隔离与架构守卫相关现有测试。

## 2. RED：两个确定性失败（修复之前真实运行）

| 用例 | 预期 | 修复前实际 | 结论 |
|---|---|---|---|
| `test_completed_child_cancels_still_running_grandchild` | Child 正常完成时仍活跃的 Grandchild 被取消 | Child `completed`，Grandchild `cancel_event.is_set() == False`；pytest exit 1（命令 `sess-55664-1207`） | **实际缺陷** |
| `test_root_cancel_cascades_even_when_grandchild_has_no_parent_run_generation` | Root 取消传播至全部后代 | 直接 Child 已取消，Grandchild 仍未取消；独立 `-k root_cancel` 运行 pytest exit 1 | **实际缺陷** |

反例完全使用 Fake LLM 和 EventStore / SessionStore 临时目录；没有调用真实 Provider。孙级创建时显式模拟生产工具派发将继承的 root run-generation 清空这一事实。

**根因 A**：`_finalize_child` 在终态后只清理本 Child，不收束其仍活跃的下级 Agent。

**根因 B**：`cancel_parent` 依赖 `ToolRegistry.cancel_session` 的 hook 继续传播取消，但其透传的根代际不一定与孙级记录的代际相同，故 hook 可能漏选孙级。

## 3. 最小改动

1. `cancel_parent(..., _all_generations=False)` 默认维持根任务代际过滤。只有在已确定直接子节点所有权之后，向其后代传播取消时使用内部的 `_all_generations=True`。
2. 直接子节点取消发生后，显式递归调用该子节点的后代取消；不依赖注册器 hook 的代际推导。
3. `_finalize_child` 在声明本 Child 已完成之前，统一收束该 Child 拥有的活跃后代。递归深度仍受原有上限和受管节点所有权约束；不增加新调度器。
4. `SubAgentResultTool` 在内存终态存在、而无法构造持久化结果绑定时，提示 `result_durability=local_only`。保持真实的本地 `completed` 结果，不伪造 `result_id`，也不自动重放未知副作用。

## 4. GREEN 与反向防护

- 两项原 RED 用例：**2 passed**。
- 新增反向测试：新 root generation 不能取消旧 generation 子树，PASS。
- 孙级取消记录先写 EventStore，再触发本地信号，且 worker 完成后 active-children 列表为空，PASS。
- 等待：Parent 在 `activity_event.wait` 中，先收到中途报告、再次进入等待后收到真实终态，均被正常唤醒，PASS；无重复轮询或额外唤醒器代码。
- 异常恢复：人为使 `EVENT_SUBAGENT_RESULT_AVAILABLE` 写入失败。本地完成可读但不能形成 settlement 绑定，工具发出 `local_only` 警告；重启只显示 `orphaned`，未伪造完成或自动重放 Provider，PASS。
- 新专项测试：**5 passed**。
- 最终定向测试（SubAgent / Delivery / Topology / Lease / RunGeneration / Architecture）：**146 passed, 1 deselected, 0 failed**（`sess-55664-1234`，8.57s）。
- Ruff changed paths：**All checks passed**；新测试文件 Ruff format 检查 PASS，`git diff --check` PASS。
- R9 静态债棘轮（独立运行，非完整 R9）：Pyright **PASS**，old debt 45/current 16/new 0，touched files diagnostics 0；`sess-55664-1230`，exit 0。

## 5. 资格与剩余限制

**本轮不是生产修复宣告**。变更仍在隔离工作树、尚未提交/合并、push、发布或重启；没有运行独立 GLM-5.3 Code Reviewer，也没有运行原版完整 R9。过去其它分支的 Reviewer/R9 结果不能替代本候选的门禁。

- `cancel_event` 是协作式停止；正在飞行的 Provider 请求或不可中断原子工具操作可能要等到实际执行返回才能退出。不能将“取消已传播”宣传成任意外部副作用已硬终止。
- 本地与磁盘结果的差异已明确暴露，但本轮不引入不安全的孤儿自动续执行。真实崩溃后若存在工具 started-but-unknown，必须按现有 WAL/租约机制只读核验并另行授权恢复。
- 着重覆盖确定性交错和既有运行路径；还未执行跨进程 kill -9、生产长任务压测、全部 Fleet 场景或完整 R9。
- 等待唤醒路径的定向用例通过，本轮**没有证据要求修改** `result_current` 的事件等待算法。

## 6. 下一门禁

在该隔离候选上冻结精确 Patch SHA；执行独立 GLM-5.3 Reviewer。只有真实 PASS 且 P0/P1 为 0，才申请/执行原版完整 R9；任何 P0/P1 要先返工并重审。合并 main、push 和发布重启需各自独立确认，不得继承本轮定向 PASS 资格。
