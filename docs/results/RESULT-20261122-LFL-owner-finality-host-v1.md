# LFL Owner 完成态可信 Host 查询 — 独立交付验收（2026-11-22）

## 冻结范围

用户明确将原长会话效率 v1.2 大范围优化缩小为独立功能：
**仅对已完成且可核验的 Goal，可信本机 Host 在模型调用前返回只读完成态回执，避免重复 Provider 调用和重复 update_goal**。
活跃长任务缩短 25%、自动 Web/Feishu 拦截、工具子集、推理档调优不属于本 PR。
原 v1.2 分支及 M0–M2/E1 证据均原样保留，不以本 PR 宣称全量目标完成。

- 源基线：本地 main 080ec9083f9e292dd31045f6b5be3d285b1c5d9c。
- 独立分支：feat/owner-finality-host-v1-20261122。
- 受管 Lane：lane-027b338e；原 Lane lane-ade617b6 以范围变更理由归档，旧分支提交 f98010fc8 保留。
- 本 PR 新增 lfl owner-finality 真实本机 Host 查询命令，不需要启动 Engine、会话、模型客户端或网络。

## 实现及权限边界

1. Host 必须显式提供 --data-dir、--workspace、--goal-id、--session，不得猜测工作区。工作区必须是产生 EvidenceRef 时的 OwnerScope（可能是历史 worktree）。
2. 命令只读 GoalStore、TaskStore、TaskEvidenceVerifier、BlobStore、EvidenceLedgerStore、RecordSearcher(kind=rule)、skill_load；Rule 固定为 RULE-AI-01，Skill 为新增 owner-finality-verify，其完整性清单仅增加一个条目，未批量批准其他漂移 Skill。
3. Goal 必须 complete、session 精确匹配；Task 全部终态、至少一项 done、每个 done Task 有当前真实且完整的 EvidenceRef，历史 verified 字段不能代替当前验证。
4. Rule 必须完整来自 SoT，Skill 必须有 integrity=ok 和五项必需步骤；任意缺失/损坏/跨 Owner/状态变化均返回 HOLD。Evidence 读锁不存在时不创建锁文件，直接 HOLD。
5. 输出 schema=lfl.owner-finality-host/v1、decision、reason、Task/Evidence 数量、model_calls=0、no_write=true、host_permission_granted=false；不返回 Evidence 内容/私密凭据。
6. NO_WRITE_VERIFIED 的退出码为 0，HOLD 为 3。此回执**不授予执行权限，不代表证据语义充分性、审批通过或实际发布完成**；Host 只能用它跳过同一 Goal 的重复终局模型调用。

## 真机正负验收

在 Mac 真实运行数据上，选取一项已完成、原 OwnerScope 可核实的 Goal，使用**实际 lfl 可执行进程**与真实 Goal/Task/Evidence/Rule/Skill 数据重复查询两次：

| 检查 | 真实结果 |
|---|---|
| Goal 状态 | complete，version=3 |
| Task / EvidenceRef | 7 项 Task，44 条 EvidenceRef，全部通过 |
| 第一次独立进程 | NO_WRITE_VERIFIED，exit 0，0.3221 秒，0 Provider |
| 第二次独立进程 | NO_WRITE_VERIFIED，exit 0，0.3232 秒，0 Provider |
| 真实数据变更 | 对账 326 个相关文件路径，SHA256 前后完全一致 |
| 错误 Owner 工作区 | HOLD，不误认其他工作区的 EvidenceRef |
| 真实 API 凭据 | 子进程已清除 LLM_API_KEY、OPENAI_API_KEY、MODEL_PROVIDERS |

真实原始回执保存在本机 /private/tmp/lfl-owner-finality-real-host-verified-20261122.json，不提交生产路径/会话标识或原始 Evidence 内容。

## 回归及发布门禁

- 新增核心、Host CLI、篡改/跨 Owner/损坏/读锁缺失/无写入/真实子进程测试。
- 单元与 CLI 兼容测试、静态检查通过；以最终 Reviewer/R9/远端 CI 的真实结果为准。
- 保持旧普通聊天路径、Tool schema、Web/Feishu/WeCom/Learning 运行逻辑不变。
- **待完成**：最终候选 SHA 冻结 → 独立 Reviewer（P0/P1=0）→ 原版完整 R9 exit 0 → 受管 PR/CI → 受保护合并 main → main CI → 单次统一受管部署与实际运行 SHA/健康/回滚验收。
- 原生大范围优化 Goal GOAL-20261122-7581f4e7 仍 active；本 PR 不虚报其全部 Task 已完成。
