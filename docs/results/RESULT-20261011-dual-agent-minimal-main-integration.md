# 双 Agent 离线闭环：最新 main 最小集成与验收

> 2026-10-11 | **Integration candidate** | 默认 OFF、无真实 Reviewer Provider 外呼、无自动接管/发布权限

## 1. 来源与明确授权

实验成果已在 `experiment/dual-agent-assurance-p0-20261011` 分三类封存：

- `2aa5b3b89` — 27 个功能文件；
- `157bd9886` — 37 个测试/守卫文件；
- `777625d1c` — 33 个设计/实验结果文件。

独立集成分支 `integration/dual-agent-offline-close-20261011` 从 `main@d3518d8ab47eecf860de06ed6466c229ce684041` 创建；未 cherry-pick 所有实验改动。本候选只包含经过依赖审计的 **13 个隔离 Python 模块**、用于主闭环/STOP/Fleet/Provider 拒绝的测试、固定 Docker 夹具、两份历史功能结果文档和本集成报告。持久化登记只移植三个实际写入面，并为 `assurance/` 登记离线实验包归属。

## 2. 迁移内容与非范围

保留的最小执行链是：

1. Executor 的真实 LoopEngine 离线写入 → 冻结候选 SHA；
2. 独立的 Task-owned LFL Reviewer OS 进程 → 隔离的原 P1.8 Docker 有界审查；
3. Host 自己执行 P1.12 的固定 311 项功能 oracle（只支持冻结的 `merge_closed_intervals` 验收），不能接受模型自报 PASS；
4. 当前 TaskControl / Fleet / STOP / 证据及会话身份二次确认 → 仅输出 `LOCAL_EXPERIMENT_VERIFIED` 或 `BLOCKED`；
5. P1.9 Provider 资格模块明确 **永远拒绝**真实物理发送（`require_provider_send_permit` 直接抛 `BrokerDeniedError`）；P1.7 仅限 synthetic FakeRemote 的停止/副作用闸门，不可在生产工具层复用。

未移植 P1.10/P1.11 三方签名/测试账户/Socket 正向实验、真实 Reviewer 供应链与 Provider Broker、额外 OCI 冒烟服务、P0 大量探索工具或生产配置、入口注册、服务重启脚本。**未合并生产 Web、Feishu、Learning、Factory、工具注册表或 Provider 路由文件。**

新增的 `test_assurance_integration_offline_only.py` 持续断言所有非 assurance 的 LFL Python 模块**不存在导入实验 assurance 包的运行时依赖**，使当前状态不能意外变成默认启用；未来真正接入必须经独立变更显式解除该冻结。所有 `may_publish` / `may_dispatch_production_effect` 仍为 false。

## 3. 验证证据

- 集成分支新 main 上的真实 Docker、双 Agent 主链、STOP/Fleet、TaskBudget 相关测试：**149 passed / 0 failed（26.71s）**，Pinned P1.8 image 与试验容器清理核验 PASS。
- 默认 OFF 静态隔离守卫、R9 持久化写入审计、包归属审计：**3 passed / 0 failed**。
- Ruff/Pyright 对移植源码及主测试 **0 新诊断**。
- 集成源码和测试提交：`0b8cfa37027713062b5a86e57528c79a7d6acf23`，30 文件，工作树干净，Git 差异检查和敏感扫描 PASS。
- **正式全量 R9：实际 Exit 0，完整链路 PASS**，机器记录 `/tmp/lfl-dual-agent-integration-r9.log`。Ruff historical=67/current=49/new=0；Pyright historical=45/current=24/new=0；环境声明扫描 826 个测试文件、遗漏 0；Tier0 **310 passed / 8414 deselected / 3 warnings**；完整 xdist 全量绿；最后架构守卫 1 passed / 20 deselected。
- 全量 CI 原脚本不保留 xdist 整体的精确 passed 数，因此不把 Tier0 310 算成整个项目的通过总数。
- 最终合并前再次确认最新 main 仍是 `d3518d8ab47eecf860de06ed6466c229ce684041`、是上述集成提交的祖先、主工作树已跟踪文件无改动（既有用户数据下的未跟踪文件不操作）。

## 4. 主分支合入条件

集成分支必须先完成 Git 文件范围/敏感扫描、原始候选 SHA 和 R9 全链路正式退出码核对；无新的全量失败之后才进行受控本地 `main` fast-forward。合并后应在 `main` 树重新核对版本与相同测试；**不执行 push、publish、service restart 或生产配置启用**。

测试通过只是双 Agent **离线功能闭环与缺陷拦截**通过；独立 GLM Reviewer 的真实语义效益、正式 Operator/OCI 签收、跨代物理 STOP 与自动接管仍是生产 NO-GO。
