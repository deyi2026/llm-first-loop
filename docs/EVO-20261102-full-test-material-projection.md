# 全量测试准入：材料投影契约、默认入口与放行判据（2026-11-02）

本文回答三件事：全量测试**用哪个入口跑**、**什么算通过**、以及 RULE-AI-28 准入
为什么曾在这棵树上**根本无法启动**、现在又如何保证强度不降。

## 1. 事实起点（2026-11-02 实测，非推测）

| 观测 | 值 |
| --- | --- |
| `review_admission start(kind=full_test)` | 拒绝：`reviewer_duration_precheck:est=7974s > hard_max=3600s (task=797380chars)` |
| 材料为何这么大 | full_test 锚定推送目的地 `origin/main`；本地领先 31 个提交 / 100 文件 / 11,756 插入，整条积压被逐字冻结 |
| 审查者预算模型 | 代码里 `est = chars / 100` 秒，`hard_max = 3600` → 材料上限约 360,000 字符 |
| 后果 | **任何有真实积压的分支都跑不了全量测试**——不是"慢"，是"永远无法准入" |

## 2. 材料投影契约

`committed_projection` 三档：

- `full`：原样冻结整条已提交 delta（git_push 仍用它）。
- `test_surface`：只逐字下发**决定一次测试算不算数**的文件，其余进清单 + 摘要。
- `auto`：能整段读就整段读（**强形式**），超 `_FULL_TEST_AUTO_PROJECT_CHARS = 330_000`
  字符才切到 `test_surface`（弱形式，且披露）。full_test 走 `auto`。

测试面判定（`_is_test_surface`）：`tests/`、`test/`、`conftest.py`、`pytest.ini`、
`tox.ini`、`setup.cfg`、`pyproject.toml`、`noxfile.py`、`Makefile`、`scripts/` 下的
`.py/.sh`、`.github/workflows/`、`eval/rules/known_reds_current.json`。理由：这些文件
一改，足以让失败的套件变绿，或让"full"悄悄缩水，审查者必须读到正文。
预算 `_TEST_SURFACE_BODY_MAX_BYTES = 150_000`，按 diff 体积**升序**填充——一个大
fixture 挤不掉其余小文件。

被投影掉的内容不是消失：

- 头部披露 `committed_projection=test_surface`、`committed_projected_files=N`、
  `committed_surface_files=M`、`committed_backlog_digest=<sha256>`；
- 正文有 `committed_backlog_manifest:` 段，逐条列出 `+added -deleted path`（≤400 条）；
- 该 sha256 是对"被投影掉路径的逐文件 diff blob"排序聚合，材料里任何一个字节变化
  都会改变工件身份；审查者可以**凭清单拒票**（例如看到 `src/evil.py +500 -0`）。

### 2.1 硬边界：投影不得把"拒绝"变成"通过"

`auto` 只在材料**本来就没超过整段复核上限**（`_REVIEWER_STATIC_MATERIAL_CAP_BYTES = 2.5MB`）
时才投影；已超上限的工件仍走原有拒绝路径。两条既有回归钉住这条语义：
`test_committed_non_runtime_monster_still_refused`、
`test_committed_runtime_projection_keeps_the_192kb_ceiling`。

## 3. 默认入口与放行判据

- **入口**：`.venv/bin/python scripts/full_test_report.py -- .venv/bin/python -m pytest tests -q -n 4`
- **唯一放行判据：新增红 = 0。**
  - 新增红（未在 `eval/rules/known_reds_current.json` 登记）→ 阻断；
  - 登记红（本次复现）→ 不阻断，但必须出现在报告里；
  - 登记红本次未复现 → 只告警（说明登记过期，另行清理）；
  - 基线缺失 / junit 损坏 → fail closed；pytest 自身崩溃 → 沿用其退出码。
- 不要把"定向测试全绿"写成"全量通过"；也不要把"登记红未复现"写成"已修"。

## 4. 本轮实测与边界

- 本仓 full_test 材料：797,380 → **278,273** 字符（est 2,783s < 3,600s），
  32 个测试面文件正文 + 68 个文件进清单。
- 定向：`tests/unit/test_review_host_admission.py` **226 passed**，ruff 全绿，
  函数行数基线按实测重登记（`_source_snapshot` 268→226）。
- **未完成**：本轮没真正跑完 14k 用例的全量套件。原因是引导顺序：闸门代码要
  publish + restart 后才生效，而 restart 的收尾是 `deferred_effect=requester_run_end`
  （等发起 run 结束）。下一轮第一条命令即可跑，不需要再改代码。
