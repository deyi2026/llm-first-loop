# Wave-3（B3 读码器 v0 + B4 读出闸门 + B7 一致性 runner）测试回执｜2026-11-25

- 命令：`../../.venv/bin/python -m pytest ctp/tests -q`（仓库 `.venv`；实际执行与审查 target 登记的是其绝对路径形态，与本行等价；未加管道）
- 工作目录：lane worktree `.worktrees/ctp-wave3-20261124`（分支 `ctp-wave3-20261124`，lane-636833fe）
- 被测内容：head `9dc0dee72ce8134c06859ed2b077d35369ae9094`（提交链：main `6349346d` → `eb88b6b92` Wave-3 候选 → `b591d8f9b` 测试准入审查 r1 修订 → `9dc0dee72` 回执 / 计划变更记录 / A.5 清单），运行时工作树干净（`git status --porcelain` 0 行）——被测内容与 head 一致
- 重放说明：本 head 由原 lane 分支（head `d9d1c55df`，基线 main `4f1157055`，链 `33706b68d` → `be8a93ba3` 并入 main → `07e2f8d16` → `d9d1c55df`）线性重放到 main `6349346d` 得到，3 个非合并提交内容不变；重放前后相对主干的差异一致（40 files，+4014 / −130）。重放前的 head 留在本地备份分支 `backup/ctp-wave3-20261124-pre-rebase-20261125`
- 环境：macOS 26.5.1（arm64），Python 3.13.13（仓库 `.venv`），pytest 9.1.1，numpy 2.5.4。本次执行会话的宿主进程处于外层沙箱：系统临时目录（`TMPDIR`）不可写，Python `tempfile` 回退到 `/tmp`，pytest 的 `tmp_path` 因此落在 `/tmp`；测试语义不受影响，如实登记
- 审查资格：RULE-AI-28 全量测试独立审查 **PASS**——r3 child `subagent_524af23f7ebf`，候选指纹 `429a47b1b8c9c2852c96032eb828b6c68e0377568c3d9fb2e53876caa9c3ab83`（执行前 status 回执 `qualification=PASS`，指纹与受理时一致；P0=0 / P1=0 / P2=4，P2 只归档、不阻塞）。审查链：r1 `subagent_cac6e9cc3c4c`（REVISE，P0=0 / P1=1 / P2=3）→ 修订提交 → r2 `subagent_fa9da6ad3f95` PASS（针对重放前的 head `07e2f8d16`）→ 候选重放到 main `6349346d` 后，r2 的 PASS 绑定的是重放前的候选指纹、不沿用，按 RULE-AI-28 对当前候选重新发起测试准入 → r3 PASS。逐轮发现、处置与修订前后对照见 `artifacts/ctp-review-20261123/code-review-20261123-findings.md` §15、§16
- **审查切片声明**：r3 的 PASS 覆盖 lane 全量 diff（11 条路径：`artifacts/ctp-review-20261123`、`ctp/docs`、`ctp/receipts`、`ctp/src/ctp_conformance`、`ctp/src/ctp_contract`、`ctp/src/ctp_reader`、`ctp/src/ctp_registry`、`ctp/tests`、`docs/PLAN-20261123-ctp-implementation.md`、`docs/governance/submissions`、`docs/trace`；切片外 tracked / untracked 均为 0）；受理后到执行前未改动 worktree。本回执的本次更新、计划第 16 章 0.3e 行与归档 §16 在测试之后才写入，不在 r3 切片内，由 git_push 审查与合并审查按 lane 全量 diff 兜底
- 执行时间：2026-11-25 08:53 前后（宿主本地时区）；以后台任务执行（job `job-f3c5835129ef40c69db0`）。放行依据是上面 r3 的 PASS 回执
- 输出（verbatim）：

```
........................................................................ [ 20%]
........................................................................ [ 41%]
........................................................................ [ 62%]
........................................................................ [ 83%]
.......................................................                  [100%]
343 passed in 2.72s
```

- 退出码：0
- **用例总数：343**（单一真值即本回执；追溯文档不手抄用例数；Wave-2 为 196；与重放前一致）
- 口径：这是 **CTP 专项定向回归**（`ctp/tests` 全集），不是仓库级全量门禁；仓库级全量结论由本 PR 的远端 canonical CI 给出
- 覆盖面（按文件列出；能力边界见对应说明文档）：
  - Wave-1 / Wave-2 既有用例（契约、不确定度、注册表、生成器、追溯矩阵机检）随本波一并回归
  - B3 读码器 v0：`test_reader_decode.py`、`test_reader_observe.py`（`ctp/docs/reader-v0-notes.md`）
  - B4 读出闸门：`test_gate.py`（`ctp/docs/gate-notes.md`）
  - 异常错误码在传播中保持：`test_error_propagation.py`
  - B7 一致性 runner：`test_conformance_receipt.py`、`test_conformance_v4.py`、`test_conformance_v7.py`、`test_conformance_v8.py`、`test_integration_reader_conformance.py`（`ctp/docs/conformance-runner-notes.md`）；其中 r1 修订新增的回归钉 27 例：不可用上限不得判 pass（12 例）、不可用分组阈值拒绝运行（10 例）、非布尔 `include_forgery` 拒绝运行（5 例）
- 边界：以上均为合成 / 数值 / 文档类测试，**不含**真实打印件实测（B8 / G3 判据），不含 V1–V8 门槛实测与 `[TBD-V4a–d]` 取值；读码器 v0 仅承诺合成图与近正对位形，平面 PnP 二义性未消解；runner 回执的 `simulated` 口径见 `ctp/docs/conformance-runner-notes.md` 与计划 §0.4
- 已知遗留（不在本波范围）：`ctp/` 下有 40 个 ruff 提示（其中 12 个在已合并的 Wave-2 文件）。CI 的 ruff 历史债棘轮范围是 `src tests scripts`，不含 `ctp/`；该闸在本工作树 R9 ruff PASS（new = 0）。测试准入 r3 的 4 条 P2（覆盖摘要构成行算术、trace.csv 字段空白、`is_limit` 不拒 inf、V8 的 `n` 强转）只归档未修，见归档 §16

## 历史运行（候选重放前，留痕）

- 2026-11-25 02:09 前后：head `07e2f8d167c11b68e9f1406fb0a063d162408d39`（链 `33706b68d` → `be8a93ba3` 并入 main `4f1157055` → `07e2f8d16`），job `job-25daa280abd041ad9942`，**343 passed in 2.48s**，退出码 0；测试准入 r2 `subagent_fa9da6ad3f95` PASS，候选指纹 `30aefa70ade85df490e74033971907222b0d71ee14a4bab3726b92797a6c97b7`，切片为 `ctp/src`、`ctp/tests`、`ctp/docs`、`docs/trace` 与归档文件（细则见归档 §15）。该 head 不在重放后的分支链上（只存在于备份分支），本节只作留痕；**用例数以文件顶部本次运行为准**

## 复现

```bash
cd .worktrees/ctp-wave3-20261124
../../.venv/bin/python -m pytest ctp/tests -q
```
