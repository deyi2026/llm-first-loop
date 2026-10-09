# R9 放行结论：isolated_transport 修复候选（2026-10-09）

## 候选身份
- 分支：`fix/isolated-transport-baseline-20261009`
- 提交：`edd762457` = 生产基线 `14352cc6f`（gen212 运行版）+ 单一移植提交
- 来源：`b74cf0c11`（i5-d 插件分支）cherry-pick，仅 11 文件 +636/−13，无插件分支（MCP/标准包，49 文件/11 提交）夹带
- 提交性质机检：`scripts/r9_commit_check.sh HEAD` 5/5 通过（fix(r9) 前缀、主路径 6 文件、diff-only、守卫文件 0 触碰、开关 3 文件 0 触碰）

## 根因（最终表述，按审查收紧）
1. 已证实：网络路径分叉——主客户端经 macOS 系统代理（Surge 127.0.0.1:6152，scutil --proxy）出网；隔离子进程被 v3 profile 强制 trust_env=False+proxy=None 直连。14:14:59 直连快败（1229ms 含 spawn），同期代理路径正常。
2. 已证实：可诊断性缺陷——worker 已回传异常类名（kind=type(exc).__name__），父进程抛错时丢弃，生产永远无法归因。
3. 不可恢复：当时 worker 实际异常（连接/DNS/TLS 哪一种）无日志留存，本结论不声称。
4. 安全侧已核实：14:14 事故中 CAS/防重放/一次物理尝试/fail-closed 记账全部按设计工作（ledger outcome=failure, phase=unknown）。

## 测试证据
| 项目 | 基线 14352cc6f | 候选 edd762457 |
|---|---|---|
| task_budget 专项 | —（261 项） | **286/286 通过**（新增 25） |
| 全量单测 | 25 failed / 7039 passed / 107 skipped (263.8s) | 22 failed / 7068 passed / 107 skipped (267s) |
| 集合差分 | — | **候选新增失败 = ∅**；候选额外修复基线 3 项 web_cutover 失败 |
| 22 项剩余失败定性 | 同款失败在基线复现（dev .env canary/模型泄漏锚定，非本变更引入） | 同左 |

## 重启链路
- 提交触碰文件与 restart 相关 = 0；`14352cc6f`/`c79d1612a` 重启加固语义原样。

## 放行结论
**放行（R9 line）**：候选满足 (1) 单一修复、无功能夹带；(2) 专项全绿；(3) 全量零新增失败且净减 3；(4) 提交性质机检 5/5；(5) 重启链路零触碰。可在授权下 Web-only publish + restart。
