# P1.12 双 Agent 主线纠偏：用实际执行任务验证 Executor → Reviewer → Gate

日期：2026-10-11。实验分支：experiment/dual-agent-assurance-p0-20261011，基线 HEAD 99cf68982。

## 裁决

**OFFLINE_TWO_AGENT_FUNCTIONAL_LOOP_PASS / LIVE_SEMANTIC_QUALIFICATION_NOT_TESTED / PRODUCTION_NO_GO。**

此前 P1.9–P1.11 偏重预算、签名、Linux UID 和隔离，主链路一直缺少一个从实际 Executor 执行任务开始的联合结果。这次**明确停止增加权限架构**，复用已存在的 LFL LoopEngine、P1 Task-owned 真实 Reviewer LoopEngine 子进程、P1.8 独立 Docker Reviewer、Task/Fleet/STOP 权威和有界 Host Gate，完整测试任务的成败与纠错。

## 本次真正实施

1. src/llm_loop/assurance/p112_offline_vertical.py：测试专用 Executor 写入工具接受来自真正 LoopEngine tool_call 的候选源码，限制唯一隔离路径和 4KiB UTF-8，O_EXCL + file/dir fsync，拒绝第二次写入或任意路径。
2. tests/integration/test_assurance_p112_two_agent_e2e.py：Executor 真实 LoopEngine 关闭一般工具注册表，FakeLLM 只驱动安全一次写盘；该 Run 完成后，使用**不同 Session、不同 OS 进程**启动独立 Reviewer LoopEngine，它只能读取冻结 candidate，输出结构性证据；再使用已有独立 Linux Docker/P1.8 Reviewer 对 frozen acceptance 进行有界真值验证。Host Gate 对比候选 SHA、Executor/Reviewer Session 分离、Reviewer 终态/工具、P1.8 Receipt/结论和当前 Task/Fleet/STOP。
3. **Gate 只可输出 LOCAL_EXPERIMENT_VERIFIED 或 BLOCKED**：即便双审核器通过，也不能发布、重启、外呼、授权任何生产 tool；R9 durability surface 为 T2 partial/default-off。

## 实际业务测试矩阵

| 场景 | 期望与实际 |
| --- | --- |
| Executor 实际写出 Python add(a,b) → 独立 Reviewer → Docker 断言 → Gate | LOCAL_EXPERIMENT_VERIFIED |
| Executor 写出错误减法 | Reviewer FAIL，Gate BLOCKED |
| 两次审核之后收到真实 TaskControl STOP | Gate BLOCKED |
| 两次审核后候选文件被篡改 | SHA 漂移，Gate BLOCKED |
| Reviewer FakeLLM 尝试 execute_command | 未授权工具，Gate BLOCKED |
| Executor 对唯一候选重复写入或增加任意 path 参数 | FAILURE，第一次 artifact 未改变 |
| 被否决的错误候选 → 显式新 attempt 重写正确内容并重审 | 新 Session/独立 Reviewer，LOCAL_EXPERIMENT_VERIFIED；旧 FAIL 无法发布 |
| 要求语义算法正确性但仅有静态有界断言 | UNCERTAIN，Gate BLOCKED |

本轮集成测试：**8 passed / 0 failed**（真实 macOS Reviewer OS sandbox + 真实 Docker Reviewer），Ruff 全绿，新增 Python Pyright 0 errors/0 warnings；架构写入面守卫 **2 passed / 0 failed**。Docker guest residual=0。

### 终态测试回执（最终候选）

| 验收 | 结果 |
| --- | --- |
| 双 Agent 主链 8 种正反场景 | **8 passed / 0 failed** |
| 主链 + TaskBudget/Fleet/STOP/独立进程相关邻接回归 | **90 passed / 0 failed** |
| 完整 R9 scripts/ci_gate.sh | **EXIT 0 / 全链路 PASS** |
| Ruff ratchet | historical=67, current=50, new=0, changed_file_diagnostics=0 |
| Pyright ratchet | historical=45, current=24, new=0, changed_file_diagnostics=0 |
| Tier0（不等于全量） | 310 passed, 8478 deselected, 3 warnings |
| xdist 未缩减全量门禁 | **全量绿**；脚本未保留精确总 passed 数，不虚构 |
| Git security scan / diff | **91 个隔离文件扫描 PASS / git diff --check PASS** |
| 冻结源码/测试/guard 文件 | **61/61 SHA256 EXACT MATCH**，manifest sha256=a1fa6939e075a9f5071e5a87ddfde9fbcb1d2f07922595837aba5c7c1d052b54 |
| P1.8 Docker reviewer 容器残留 | **0** |

完整测试回执文件位于 /tmp/lfl-p112-ci-full.log、/tmp/lfl-p112-e2e-final.log、/tmp/lfl-p112-targeted-adjacent.log。当前候选来源于实验 HEAD 99cf68982 + 未提交 P0～P1.12，而非当前 main d3518d8ab 的合并构建，因此 R9 PASS **不能**视为生产合入后的验证。原有静态历史债尚在；new=0 不等于全树零诊断。

## 重要限制，不能虚报

- Executor / Reviewer 的 LLM 是**注入 FakeLLM**，没有对 GLM-5.3 的真实任务能力与独立语义审查效果做 A/B；P1 macOS 子进程的结构性回执绝不等于独立 Review Gate PASS。
- P1.8 Docker Reviewer 只执行有界字面断言（匹配与排除）；不执行任意用户代码，也不能证明复杂算法语义。若任务含 SEMANTIC_REVIEW_REQUIRED，则必须是 UNCERTAIN，Gate 不能通过。
- 修复验证使用显式**新任务尝试/新隔离 TaskControlStore**，而不是声称已实现同一持久 Task 的自动 revise/version CAS。
- 现有 Gate 是 Host 端 **local-only 测试接收裁决**，完全不同于生产发布或效果工具授权。没有 Provider 真实计费、Web/Feishu 通道集成、真实 Stop 物理发送栅栏或独立安全身份放行。

## 可复现命令

在现有隔离 worktree 下：

    LFL_ASSURANCE_REAL_DOCKER_PROBE=1 \
      LFL_ASSURANCE_P18_IMAGE_REF='lfl/assurance-p18-reviewer@sha256:342e7adc24ba760b7acd3b9edd8b17b939c840a99d4ce2fc353a40825f994608' \
      PYTHONPATH=src ../../.venv/bin/python -m pytest -q \
      tests/integration/test_assurance_p112_two_agent_e2e.py

macOS 需 /usr/bin/sandbox-exec 且 Docker 需本地已有准确 RepoDigest；有界离线运行必须禁止 provider 外呼。不运行任何不明确的自动工作流或发布。

## 后续唯一合适的主线

如后续推进真实模型验收，应选择**一项用户实际任务**，在冻结预算、有效操作员签发、Stop/Fleet 物理围栏和独立 Reviewer 原始证据已合格的前提下，单次 GLM-5.3 Executor/Reviewer A/B，对比正确率、误判、返工率、总成本，并继续将生产释放独立审批。不要再以不断新增身份/签名子阶段代替实际双 Agent 效果验证。
