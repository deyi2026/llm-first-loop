# Web-only direct-child Canary Host：最新 main 隔离集成再验收

> 日期：2026-10-16。**仅隔离集成；未合并 main、未 push、未部署、未重启、未运行真实生产多 Agent Provider canary。**

## 精确身份

- 主线**已提交**快照：`c3c306f6d2c2d6684219daa624604c0edd7e294d`。当前主工作树另有其他 Agent 的未提交修改（不纳入本轮评估）。
- 新隔离分支：`fix/web-multiagent-canary-main-integration-20261016`。
- 新候选行为提交：`9638470002f3063c2272cc5e4d9465f5e461ac20`，含原隔离实现 cherry-pick 与 Registry 最小修复。
- 审查范围：10 文件；`git diff --binary c3c306f6d2c2d6684219daa624604c0edd7e294d 9638470002f3063c2272cc5e4d9465f5e461ac20` 的 SHA-256：`46a4f314c18a1524276e85c1977589062180ea12e5d0416db4de84646960113e`。
- 原九文件独立候选审查与 R9 **没有冒用**，本次是新十文件的独立审查和原版 R9。

## 已证实 RED → GREEN

真实 `ToolRegistry.execute` → `SpawnSubAgentTool.execute` → `SubAgentRunner.start`
→ `SubAgentResultTool.execute` 的 **Provider-free** 物理调度路径发现：
`requires={"tools":[]}` 原来在 Spawn 工具处因 falsey 元组转换成 `None`；
新 Canary Host 因 `required_tools != []` 拒绝，实际工具返回 `subagent_canary_child_scope_denied`。

- 初始 RED：`1 failed`，物理退出 1；原始日志 SHA `e405546e3a8cdf5d217b37ed0e352b787efd9ab04f8f33796b5b717bd2485ce4`。
- 最小修复：显式声明 `tools` 键时，即使空集也传递 `[]`；未声明仍传 `None`；**未放宽子工具权限**。
- 修复后 GREEN：`1 passed`，物理退出 0；日志 SHA `8102f7783881d95099cdc88d35bb159d295c1b522aec682410169025fe7931a0`。
- 跨模块定向回归：**184 passed，0 failed**；SHA `eac6c266ea62cb1652346eacf908a8c87f67da5208fada2e676e4ac65e1111d1`。
- 一次定向命令初始引用了另一 Agent 未提交的测试文件，pytest 收集前因不存在退出 4、`no tests ran`，已保留私有日志；随后以正确的已提交集合进行本次 184 项实测。

## 独立 GLM-5.3 Reviewer

Reviewer 实际终态 `completed`，一个真实零工具子 Agent，恰好一个模型调用，禁止自动重试，
机器尾行匹配精确十文件差分。结论 **PASS，P0=0、P1=0、P2=3**。

三个非阻断提醒：`requires` 缺省时多层拒绝职责要保持；传输上下文跨线程传播需上线专项验证；成功续轮与八次共享物理尝试上限的关系应明确说明。
原始 Reviewer JSON SHA `4ddcb71034aae23ab625be1bbeb632fa8348de95df74d3a1c4ec1e05d5242e14`。

## 原版 Quick / 完整 R9 — 如实区分两种 PASS

| 证据 | 结果 |
| --- | --- |
| 原版 Quick | 物理退出 0，Tier0 **319 passed** |
| Ruff/Pyright | 新增诊断 0；修改文件诊断 0 |
| 完整 R9 xdist 首轮 | **9,097 passed，146 skipped，1 failed** |
| xdist 失败点 | `tests/phase6/test_m1_sync_interrupt.py::test_s4_multiple_interjections_all_consumed`，HTTP 409 vs 202 |
| 原脚本 D-B2-09 串行单文件复核 | **9 passed，0 failed** |
| 原版 R9 物理退出码 | **0**，按现有 D-B2-09 策略判为 Gate PASS |
| 原版 R9 原始日志 SHA | `c44a712575543b740919a42462dbe617eff0fcffe82951583d1e01b8edae4772` |

**不宣称首次 xdist 全绿。** D-B2-09 原生允许“xdist 红、串行绿”作为分布假红观察；该事实并不排除未知底层并发竞态。失败用例未位于本次 10 文件差分中，尚无独立 clean-main 因果归因，不把它擅自归因给本修复或宣称其必然无关。未自动追加完整 R9 第二次运行。

全量测试在本隔离工作树生成的 18 个历史 report 文件变动已单独归档（SHA `c22b81fc59756979b9e7f675ec323c59eb089fe7e41f34a118caa00b457d278c`）并仅在此树恢复，重新核验源补丁 SHA 未改变。

## Main 工作树并发风险与后续闸门

截至收口时已提交 main 仍 `c3c306f6d2c2d6684219daa624604c0edd7e294d`；主工作树由其他 Agent 留有 **28** 条 status 变动。
其中与候选路径直接重叠：` M src/llm_loop/subagent/runner.py,  M src/llm_loop/tools/builtin/spawn_subagent.py`。另外 `execution_surface.py`、`scripts/ci_gate.sh` 等在 root 处也有未提交变化，不属于这轮 frozen main。
本次仅验证 **已提交 main 快照**，未覆盖其他 Agent 未提交的现场代码，亦不能授权直接覆盖它们。

**结论：隔离候选审查 PASS；原版 R9 按 D-B2-09 策略 PASS，但首次 xdist 有 1 个失败观察项。**
本地 main 合并尚无授权且 root 存在并行变化，当前不执行合并。后续应待其他 Agent 收敛，
核验当时的真实 main 和交叉修改；如来源版本或代码变更，必须重新冻结/重新满足集成闸门。
本轮没有 push、发布、服务重启或生产 Provider 多 Agent 实验。

## 回执

- 独立审查：`docs/governance/receipts/RECEIPT-20261016-web-multiagent-canary-main-integration-independent-glm53.json`
- 原版 R9：`docs/governance/receipts/RECEIPT-20261016-web-multiagent-canary-main-integration-original-full-r9.json`
- 原始 Reviewer/RED/GREEN/Quick/R9 日志、报告差分：隔离工作树 ignored 目录
  `data/web-multiagent-canary-main-integration-20261016/`
