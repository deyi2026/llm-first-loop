# Learning 删除会话修复：最新完整 main 597 隔离集成和 Quick 门禁

日期：2026-10-16（UTC+8）。**全部结果仅属于隔离分支；不是完整 R9 或生产上线资格。**

## 范围和代码身份

- 原项目并行 Goal `GOAL-20261015-ac085ab1` 的任务账本 004（独立审查）、005（原版全量 R9）、006（封存）已真实登记 `done`，且各有 3 个 `evidence://v1/` 引用。其提交链依次为 `c72a615c`（Batch B）、`02c7a5382`（P1/ledger）、`4df9ac373`（守卫登记+full-test receipt）、`597732ed1d292aed4879c9ba8d70ab6f2c6460cd`（T6 delivery report）。
- 本轮从此 exact full main 基线，在隔离 worktree `.worktrees/learning-source-deleted-597-integration-20261016`、分支 `fix/learning-source-deleted-597-integration-20261016` **只** cherry-pick 已审 Learning 源码 e49e3e0 与旧三份独立审查/R9历史回执。
- 新源码 commit `b1fc63ef1e9b348587ce076a8f57b779ff1d6f65`，回执 commit `b6d0acf55cf5cbb83ba51fc5665ce00b4cca24a8`。两文件完整 Git binary patch **5,550 bytes SHA-256 `925e453fd5baf1632eaa305134a47b2b198762dc26af8b0d222d1bec50981e89`**，与独立GLM-5.3 Reviewer先前在 af4 基线审查的源码补丁完全一致，但**新main transitive imports/行为仍应独立审查**。
- 未修改根 main、未干扰 owner 的 index 或 18份原版R9自生成tracked报告，不推送、不部署、不重启或修改 Provider/G4。

## 新 main 597 + Learning 的真实 provider-free 结果

| 验收动作 | 实际结果 / 日志 SHA-256 |
| --- | --- |
| 9个文件：8个 Learning + 1个新 `test_use_ledger_contract.py` | **136 passed, 0 failed, 1 warning, exit 0**；忽略日志 `data/learning-source-deleted-597-integration-20261016/learning-ledger-focused.log`，SHA `17f0a67595b6619729ee608cc9566e2126657125809df198770f50bd7c5c6188` |
| 前次Quick失败的2个架构守卫 | **2 passed, 28 deselected, exit 0**；`guard2.log` SHA `5aa62b66d7ce582e5fa16fa47972059474e3a6e6d037f1a95308359f8f92d5d0` |
| Ruff 两个Learning源/测试 | **PASS** |
| 原版 `bash scripts/ci_gate.sh --quick` | **真实退出码0**，RuffPASS、EnvPin866 filesPASS、Pyright1.1.411 new0PASS、Tier0 **319 passed, 8875 deselected, 3 warnings**；完整 `quick.log` SHA `0044c9502506840f723fbb430c1c689679cc6350ec6b2fe0d2cbfc5e4c5ab664` |

- 为确保无 Provider 调用，明确移除了命令环境中的 GLM、GLM Reviewer、OpenAI、Anthropic、DeepSeek keys；沿用原先已试验的**Python-only** socket/DNS guard `sitecustomize.py` SHA `a66fd43421b2f3232bbd5b7960339ea3e988c6c47aa8a442283a9ae110866961`；**不能声称全 OS/非 Python 进程均被隔离**。
- `quick` 依照项目规则 `R9-WF-01c` 本身声明“quick 模式止于预检：不构成提交门禁”，**不能以319pass代替完整R9**。
- 上一组 c72a/main 中10个Missing `llm_loop.use_ledger` 导入错误，已通过owner的新main实现完整依赖在9文件定向测试中消除。中间02c7/main中两项架构守卫Quick失败，也通过owner 4df登记修复并在此次干净597组合通过。
- 原旧 af4 + Learning 的 **8,977 passed/146 skipped/0 failed** 是旧基线证据，不能替换新597组合的独立审查或新全量R9。

## 仍需独立准入与授权

1. 新组合现在仅 **ISOLATED QUICK QUALIFIED**，未取得**面向最新597运行上下文**的独立CodeReviewer 终态和本次源码+base身份绑定。依据 Rule28，后续完整R9之前必须先独立代码Reviewer PASS P0/P1=0，并针对复审意见只在隔离分支返工；若patch变化，应重新冻结SHA和审查。
2. 审查PASS后方可在稳定且干净的候选身份运行原项目的完整R9，存储真实原始日志SHA、xdist/serial、skip和exit，不能从owner的旧main原版测试代推新Learning组合。
3. 这两项都通过后才能向用户申请**精确本地 main 合并授权**。根main先前还有别的Agent全R9生成的18份tracked reports，未经owner明确归属确认/回执不能擅自恢复或清理；合并之前必须再次确认清洁、安全时机与并行会话。
4. 发布还需要单独申请**Learning-only** 授权并验证 queue/inflight、受管CAS generation、已知good rollback c8e50cb2、生产正/负canary回执。严禁未经授权push、重启Web/Feishu或变更Provider。

本文件仅在本轮独立候选分支落盘并进行 git security scan；不是main/生产状态变更记录。
