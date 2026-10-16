# Learning source-session-deleted 修复：main c72a 集成预演及干净基线 A/B 证据

- Date: 2026-10-15（本地 +08），限定性质：**独立分支 provider-free 预演，非生产上线许可、非完整 R9、非独立 Reviewer 的新结果**。
- 新 main 基线：`c72a615c099363ce69fd83b2aa1ff33c4f94ad34`，由并行 `GOAL-20261015-ac085ab1` 提交 Batch B 审核回执与 factory/settlement 检索链。
- 学习修复原冻结基线 `af4e26fae9ef78263de486ec6e7f01123aed453f`，原代码提交 `e49e3e03769e2366474d51a14a4c9efc16afb87a` 和三文档提交 `0027e7a3a84fbe3af364633d7f0f9d099d377298`。
- 本轮**仅在独立 worktree** `.worktrees/learning-source-deleted-c72a-integration-20261015` 顺序 cherry-pick 两提交；结果新代码提交 `5bc16d45414405a79b252e46dd019956ee89d248`，新文档 HEAD `c9e27c90e686cb27ff6af07183b2dacfccc81c3f`。新 main 相比原基线变更 11 路径，原 Learning 改动 5 路径，交集 **0**；只读 Git 三方预演没有冲突。
- Learning **仅 src/llm_loop/methods/learning_plane.py 和 tests/unit/test_learning_plane_memory.py** 的 Git binary diff：**5550 bytes SHA256 `925e453fd5baf1632eaa305134a47b2b198762dc26af8b0d222d1bec50981e89`**，和 af4 原独立 Reviewer 审查的源码补丁完全一致；不代表合并后的工具图与整个 main 已通过新审查。

## 精确对照（完全相同的八个真实测试文件）

| 基线 | 实际 pytest 物理退出 | 通过 | 失败 | 失败用例集合/原因 |
| --- | --- | ---: | ---: | --- |
| 干净 `main c72a615c` 无 Learning 修复 | `exit 1` | 101 | 10 | `ModuleNotFoundError: No module named 'llm_loop.use_ledger'`（10/10） |
| 同 `main c72a615c` + Learning 修复 | `exit 1` | 104 | 10 | **同样 10 个失败用例，名称完全一致；相同 ModuleNotFoundError 10/10** |
| 组合候选上只执行 3 个新 Learning 回归 | `exit 0` | 3 | 0 | 5 deselected；3 个目标行为 PASS |

- 相同八文件包括：`test_learning_plane_memory.py`、`test_learning_plane_admission.py`、`test_learning_journal.py`、`test_memory_extract.py`、`test_session.py`、`test_session_external_resource_delete_fence.py`、`test_learning_foreground_independence.py`、`test_learning_idle.py`。
- 完整日志（本隔离工作树 ignored private evidence）：`data/learning-source-deleted-c72a-integration-20261015/baseline-c72a.log` SHA256 `f98e1c4241b3782c8ceb61e34b431f85673de9bf4f8d297757f04a743ebbe171`；`focused.log` SHA256 `adf772aa227506391124ff7c1e8dbcce62f9d14d0dc30eb0671896d0139813d2`；`learning-3-tests.log` SHA256 `6f17d6e13da5136907c5cdef07b4946d365d6e8e7bcb935ea5e55dbb6b8e06b3`。
- touched Learning 两个 Python 文件 Ruff `All checks passed!`；没有启动原版完整 R9；没有执行任何真实 Provider 请求（测试环境清除了主流Provider变量）。

## 上游根因与有效责任边界

`main c72a615c` 已包含 `src/llm_loop/introspection/settlement.py:37` 的 `from llm_loop.use_ledger import derive_slot_id, derive_submission_hash`，但其 tree **不存在** `src/llm_loop/use_ledger.py`。原并行任务主工作区当时 `AM src/llm_loop/use_ledger.py`，尚未成为该已提交 Git tree 的一部分。10 项 factory/实际初始化相关失败在 main 自身就能稳定复现，因此**不能归因于 Learning 修复**，同时也**不能说组合 R9 合格**。

该依赖归属原项目 owner `GOAL-20261015-ac085ab1`，不可在本 Goal 擅自拷贝它的未提交文件，不可为规避缺口修改测试/跳过 CI，也不可抢先合 main。特别要保留并行 Goal 最新 `004` 独立 CodeReviewer 通过、`005` 原生 Full R9 真 exit、`006` 已提交/封存 的闭环链；旧的独立 Reviewer PASS 必须对绑定补丁 SHA 有效。当前 root 仍有其它Agent的 staged+unstaged 资产和活跃会话，不能认为已完成。

## 重新准入触发条件（不是自动授权）

1. 并行 owner 合法收口其模块依赖、Reviewer/Full R9 和封存，提供真实最终提交和回执；**主线必须是 Git clean checkout 中真实可导入的完整版本**。
2. 从当时最新完整 main 建立新隔离集成候选，验证新修复前 baseline 与组合后的确切缺陷归因、差分及所有 CodeReviewer fingerprint currentness。若源码/作用面或 Review 资格漂移，需新的独立 CodeReviewer PASS P0=P1=0，且在任何完整 R9 前满足 Rule28。
3. 在严格干净候选与相关操作不冲突的条件下执行原版 Full R9；记录真实 exit、xdist/serial、skips、test log SHA、git patch identity。取得专门人类**本地 main 合并授权**后才能更新 main；不得利用此备忘录授权 push/发布/重启。
4. Learning-only 发布需额外获取独立明确授权、重新核对 journal queue/inflight、consumer idleness、旧版 `c8e50cb2` 可回滚、CAS generation、受管动作 terminal 和真实 positive/negative canary。不影响现有 Web 和 Feishu。

**Terminal disposition:** `ISOLATED_LEARNING_PATCH_VALID, INTEGRATED_MAIN_NOT_QUALIFIED — WAIT FOR UPSTREAM OWNER ATOMIC DEPENDENCY & REAL R9/REVIEW CLOSURE`。原始 af4 的 8977 pass/146 skip/0 fail 仅说明旧基线，不延伸宣称 c72a 联合代码已达原版全量资格。本备忘只在隔离分支，不发布、不推送。
