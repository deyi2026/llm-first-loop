# Wave-2（B5 注册表 + B6 生成器 + A2/A3 文档）测试回执｜2026-11-24

- 命令：`../../.venv/bin/python -m pytest ctp/tests -q`（仓库 `.venv`；审查 target 登记的是其绝对路径形态，与本行等价；未加管道）
- 工作目录：lane worktree `.worktrees/ctp-wave2-20261124`（分支 `ctp-wave2-20261124`，lane-4bbd8c8e）
- 被测内容：head `e085e3bd368574e33ff26d2cfb487a98c1d46462`（提交 `cdbd4d95c` → `f4c014d06` → `4411232fe` → `f465fc091` → `e085e3bd3`），运行时工作树干净（`git status --porcelain` 0 行）——被测内容与 head 一致
- 环境：macOS，Python 3.13.13（仓库 `.venv`），pytest 9.1.1，numpy 2.5.4，cryptography 50.0.2，jsonschema 4.26.0，reportlab 5.0.1
- 审查资格：RULE-AI-28 全量测试独立审查 **PASS**——child `subagent_33409f675de7`，候选指纹 `d4d8cff2eacf96d36d3eee43a50544c5bd197e8a7cf577369ed5d9677b456a8b`；审查链 r1 `subagent_84e2886b6b17`（REVISE 1P1+4P2）→ r2 `subagent_5a5be205c44e`（REVISE 1P1+3P2）→ r3 `subagent_6014966192ff`（PASS，但首次执行暴露收集期 ImportError 并已修复）→ r4 `subagent_5fe38d0fec27`（REVISE 1P1+4P2）→ r5 `subagent_4b59fb2dc085`（reviewer_timeout ×2，无结论）→ r6 PASS。逐轮发现与处置见 `artifacts/ctp-review-20261123/code-review-20261123-findings.md` §8–§12
- **审查切片声明**：r6 的 PASS 覆盖 `ctp/src`、`ctp/tests`、`ctp/schema`、`ctp/README.md`、`ctp/docs/{registry-notes,generator-notes,uncertainty-declaration-template}.md`、`ctp/receipts`、`docs/trace`；`docs/conformance/` 与 `ctp/docs/upstream/` 不在 r6 切片内（前四轮已审、不参与测试执行，收窄原因与残余风险见 findings §12），由合并审查按 lane 全量 diff 兜底
- 执行时间：2026-11-24 17:3x（宿主本地时区）；以后台任务执行（job `job-4a52ee459fc647ab85df`）
- 输出（verbatim）：

```
........................................................................ [ 37%]
........................................................................ [ 75%]
..............................................                           [100%]
190 passed in 2.30s
```

- 退出码：0
- **用例总数：190**（单一真值即本回执；追溯文档不再手抄用例数）
- 覆盖面：
  - B1 契约：10 合法 + 24 非法 fixture、schema parity 六条分歧规则族（R1–R6）、错误码与字段路径断言、NaN 注入拒绝、协方差单位回归钉
  - B2 不确定度：模板声明、deg→rad 换算、一阶 vs MC ≤5%、应拦输入（60° σ 判失效、θ→π 奇异、非 PSD、奇异协方差、全零 1σ、力臂耦合）
  - B5 注册表：R-1–R-6 正负例（append-only 链、改写/删行检测、墓碑复用拒绝、两级签名快照与篡改拒绝、绑定验签、两级时效、retire 权威钩子、created_at 时区、墓碑 ID 不回快照）
  - B6 生成器：36h11 码表不变量、布局校验、确定性再生成、清单防篡改、PDF 有效性、混页尺寸拒绝
- 边界：以上为合成/数值/文档类测试，**不含**真实打印件实测（B8/G3 判据）、不含 V1–V8 门槛实测（A2 规程对应的 conformance 行仍为 pending）；`simulated` 口径见计划 §0.4

## 第二次运行（合并前验收补齐之后）｜2026-11-24

- 命令：`../../.venv/bin/python -m pytest ctp/tests -q`（仓库 `.venv`；实际执行与审查 target 登记的是其绝对路径形态，与本行等价；未加管道）
- 工作目录：同上（lane worktree，分支 `ctp-wave2-20261124`）
- 被测内容：head `4c39db79ca3a1171017365d3c02696c26b5a8dd6`（上一轮 head `e085e3bd3` 之后：`b0dce10a9` 上一轮回执 → `394b94a1a` 并入 main（含 PR #115）→ `4c39db79c` 合并前验收补齐），运行时工作树干净（`git status --porcelain` 0 行）
- 审查资格：RULE-AI-28 全量测试独立审查 **PASS**——child `subagent_e6dd98e3f3e4`，候选指纹 `97778d0cce8308eb97e9d02cd345069904885b7627b405fa1db90afba4c9b6b4`；审查切片与上一轮 r6 相同的 9 条路径，切片外 tracked / 未跟踪均为 0；本轮审查期间未改动 worktree
- 执行时间：2026-11-24 19:1x（宿主本地时区）；以后台任务执行（job `job-87365e91e61f455baaf9`）；环境同上
- 输出（verbatim）：

```
........................................................................ [ 36%]
........................................................................ [ 73%]
....................................................                     [100%]
196 passed in 2.51s
```

- 退出码：0
- **用例总数：196**（最新单一真值；上一轮为 190）
- 相对上一轮新增的用例：B6 布局 `frame_ref` / 逐码坐标 / 公差标注 3 例（1 正例 + 2 应拦）；追溯矩阵机检 3 例（每个测试函数具名、文档计数等于 AST 实测、证据行号指向 def 行）
- 本轮补齐但**未**被测试覆盖的内容：8 份规程的最小冒烟步骤属文档，其中的冒烟板命令与 V5、V6 两条命令在本机以同一解释器单独实测通过（输出 `manifest_ok True` / `coarse` / `first_order_ok True`），不产生门槛证据
- 边界同上一轮：不含真实打印件实测（B8 / G3 判据），不含 V1–V8 门槛实测

## 复现

```bash
cd .worktrees/ctp-wave2-20261124
../../.venv/bin/python -m pytest ctp/tests -q
```
