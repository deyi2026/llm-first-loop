# LFL 开发流程 v1.1：实施范围与需求映射

> 来源：`DESIGN-20261120-LFL-development-test-and-requirement-closure-v1.0.md`，原始 SHA256 `c839796491181de341a241d3a4af7259ab9997414111138a97a4ff70752a3f52`。
> **状态：开发中，不是已验收**。7 个 Task ID 已通过真实 LFL CLI（`glm/glm-5.3-flash`）在可信会话创建并经 TaskStore 只读核对，全部仍为 `pending`、`evidence_required=true`；这只证明登记完成，**不证明实现完成**。
> MCP Console 持久 Goal：`76594f16-d7be-44bc-a989-cd9cb650a74f`；LFL 原生 Goal：`GOAL-20261120-022593f7`；代码 Lane：`lane-1a2b434b`（旧外部引用 Lane `lane-1f62559a` 已带审计原因关闭，不是合并）。

<!-- LFL-REQ-GOAL: GOAL-20261120-022593f7 -->

## 必需需求与测试设计

<!-- LFL-REQ-MATRIX:v1 -->
| REQ | Task | Slice | Required | Acceptance | Incremental | Final | Scope approval |
| --- | --- | --- | --- | --- | --- | --- | --- |
| REQ-FLOW-001 | TASK-022593f7-001 | A | yes | 设计与测试同步定义并保持规则单一真相源 | tests/unit/test_goal_coverage.py | R9,CI | - |
| REQ-FLOW-002 | TASK-022593f7-002 | A | yes | 需求范围与TaskStore双向对账且遗漏不放行 | tests/unit/test_goal_coverage.py | R9,CI | - |
| REQ-FLOW-003 | TASK-022593f7-003 | B | yes | 开发期增量测试覆盖新增和影响面且不假PASS | tests/unit/test_dev_gate.py | R9,CI | - |
| REQ-FLOW-004 | TASK-022593f7-004 | B | yes | 受限开发提交保留锁和安全扫描且无法获取发布资格 | tests/unit/test_r9_commit_dev_mode.py, tests/unit/test_dev_commit_flow.py, tests/unit/test_dev_commit_host_authority.py | R9,CI | - |
| REQ-FLOW-005 | TASK-022593f7-005 | C | yes | Goal完成需全部必需需求与可信证据且取消不等于完成 | tests/unit/test_goal_finality_evidence_gate.py, tests/unit/test_goal_requirement_scope_gate.py | R9,CI | - |
| REQ-FLOW-006 | TASK-022593f7-006 | C | yes | 正式集成验收树与部署树一致且四服务健康可核验 | tests/unit/test_goal_coverage.py | R9,CI,DEPLOY | - |
| REQ-FLOW-007 | TASK-022593f7-007 | C | yes | 代码质量不增加重复状态和无效兼容层且效率有实测 | tests/unit/test_goal_coverage.py | R9,CI | - |
<!-- /LFL-REQ-MATRIX -->

## 阶段出口

- A：模板/只读覆盖检查及负测；在真实 Goal 上跑影子报告，缺失项明确列出，不改变现有完成门禁。
- B：增量测试选择器及受限开发提交负测；默认完整门禁不变，涉及安全/Host策略变更另行批准。
- C：需求完成门禁、真实多 REQ 试点、独立 Reviewer、原版完整 R9、受保护 PR/CI、main CI、受管部署和健康回滚验收。

**当前明确未完成**：7 项 Task 均未完成、真实增量开发闭环、正式 Reviewer/R9/PR/CI、main 合并与部署。不能因这份文档或影子报告 PASS 宣称任何一项完成。

## 2026-11-20 隔离实证与验收差集

- **A（隔离候选已实现）**：设计/测试规则 SoT、7 REQ ↔ 7 原生 Task 绑定、只读双向覆盖检查；原生 Task 均 pending，影子核验按预期 BLOCKED。
- **B（受限影子实现）**：`scripts/dev_gate.sh` + `scripts/dev_gate.py`、AST 静态/常量动态导入、未知动态依赖与 symlink 拒绝、monkeypatch 影响选择、精确 base/工作树/设计/TaskStore/测试指纹、Lane 归属及跨 Lane 依赖核对。窄范围曾实际运行 3 个测试文件 Ruff/Pyright/Pytest exit 0；当前共享 `goal.py` 等核心文件触及 569 个测试文件、共享 conftest、未知动态 import 和其他活跃 Lane 依赖冲突，**正确返回 BLOCKED**。
- **受限提交候选已实现、仍未启用**：`r9_commit.sh --dev` 复用提交锁/PROBE/机检/安全扫描，执行增量门后请求独立 Host 一次性消费；专用 Ed25519、root-owned 精确树审批/激活、Host-owned 防重放账本均有隔离单测，临时 Git shell 正负 E2E 已通过。**生产 Host 未安装/激活，真实 `--dev` 仍 exit 78；没有正式 Host 签发资格，也未执行实际开发提交**。
- **C（隔离候选已实现、尚未生产验收）**：一次性 owner/CAS/设计SHA绑定与 REQ 专项 `complete_gate`，旧 Goal 兼容、取消/遗漏/证据漂移/设计篡改均有负测；须合入后用真实 owner 会话绑定本 Goal，再进行真实完整闭环。

| 设计用例 | 当前结果 | 证据/剩余缺口 |
| --- | --- | --- |
| T-01～T-04 | 局部 PASS；高扇出变更 BLOCKED | `test_dev_gate.py`：选择、空集、动态引用、静态失败及异常输入 |
| T-05 | 隔离测试 PASS；真实 Host 待验 | 陈旧 base、Lane 归属、脏输入、环境伪造、索引白名单拒绝；临时 Git 仓验证锁/PROBE/精确提交 |
| T-06 | 隔离负测 PASS；生产仍禁用 | `test_r9_commit_dev_mode.py`、`test_dev_commit_flow.py`、`test_dev_commit_host_authority.py`：独立签名/一次消费/越权拒绝；真实 Host UID/授权待验 |
| T-07～T-09 | 隔离单测 PASS | `test_goal_coverage.py`、`test_goal_requirement_scope_gate.py`：REQ 遗漏、cancelled、SHA/证据漂移 |
| T-10 | 隔离单测 PASS，真实影子 BLOCKED | 不同文件的跨 Lane 反向依赖冲突被发现，待协调后重验 |
| T-11 | 部分 PASS | 必需 REQ 未完成时终局拒绝；真实分批合并试点待做 |
| T-12 | PASS | 41 REQ 触发 `goal_task_limit_exceeded`，不静默丢项 |
| F-01～F-09 | **全部待正式验收** | 独立 Reviewer、原版完整 R9、首轮失败处理、PR/CI、main、部署、真实 Host/四服务回执 |

效率基线只能记录已观测值：窄范围开发门禁曾在约数秒内执行 3 个选中测试文件；核心 Goal/TaskStore 影响扩散后触发过宽阻断。**不得据此宣称整体提速或最终质量提升**；待真实试点统计 P50/P95、全量次数、返工和缺陷。

## 绑定修订记录

- 2026-11-20：初稿 `TASK-UNBOUND-001..007` 明确占位，影子核验按缺 TaskStore 拒绝。
- 2026-11-20：经独立真实 LFL CLI session 创建 `GOAL-20261120-022593f7` 和 7 个原生 Task；用真实 ID 逐行替换占位，旧 Lane 终态归档，新 Lane `lane-1a2b434b` 绑定原生 Goal。所有任务保持 pending，未洗白为完成。
