# held-out 隔离：从规则到运行时机制

> 日期：2026-10-25 ｜ 规则真值源：`eval/rules/holdout.md` §4 ｜ 落地代码：`src/llm_loop/knowledge/heldout_guard.py`
> 状态：**运行时已接线并通过独立审核**；eval 知识库状态显式化已落地（§6-1）；held-out **尚未实跑**。

## 1. 为什么做

`eval/rules/holdout.md` §4 要求"任何写入 method/experience/lesson/episode/memory 载体的操作，必须先对照
forbidden_task_ids 与题面过滤"，但 2026-10-25 之前：

- `evals/heldout/v1/filter.py` 存在且 `--selfcheck` 通过，**但 `src/` 全域 0 处引用** → 只有规则与离线脚本，没有强制。
- 该脚本本身有两处不成立：读 `exclusion.forbidden_statement_sha256`（manifest 中不存在 → 恒空集）；
  且拿"规范化文本 sha256"去比对 manifest 里的"文件字节 sha256"，语义不可比。
- 结果是：隔离依赖"模型自觉 + 人眼检查"，而不是机制。

## 2. 机制（现在是什么）

| 面 | 行为 | 失败模式 |
|---|---|---|
| 检测 | 每 task 造 **24 字 / 步长 4** 重叠探针（上限 16 个）+ task_id | 24 字窗口保证任意 ≥32 字连续引用必含一个探针（32 字片段含 9 个窗口起点，必覆盖 4 的倍数） |
| 写侧 | method `save_candidate` / `annotate_aliases` / `annotate_freshness` / `record_use`、experience `save` / `record_use`、memory `save_entry[_if_observed]` | 命中 `blocked` → 抛 `HeldoutContaminationError`，**零落盘**（校验点在最终载荷、提交之前） |
| 读侧 | `search_records` 的 method/experience 检索（含精确水合） | 命中行丢弃，写 `_last_heldout_filter` 计数 + `_LOGGER.info`（只含 kind/reason/task_id） |
| 守卫自身 | manifest 缺失 / JSON 坏 / 内部异常 | `unavailable` → **放行**（fail-open），不阻断正常知识写入 |
| CLI | `evals/heldout/v1/filter.py` 收敛为薄 CLI，委托 src | `--selfcheck` 0/1；`--text` 命中 2 |

关键设计取舍：

- **probe 而不是 hash**：manifest 的 sha 是文件字节哈希，与"引用了一段话"这种泄漏形态不可比。
- **不做 n-gram 覆盖率**：多探针子串可解释、可造反例，够用且快。
- **检查"最终落盘载荷"而不是入参字段**：早期版本按 name/description/body 手工拼，独立审核用真实 task_id 证明
  `aliases`、`annotate_freshness` 的 `freshness_refs`、`record_use` 的 `note` 三条旁路能绕过去。现在统一在
  canonical 载荷上校验，别名/来源/注记都在检查面内。
- **读侧整行检查**而非字段白名单：同一轮审核证明白名单会漏掉 `recent_issue`（由 usage 注解阶段注入）。现在对最终
  返回行整体序列化后检查，且过滤放在所有注解之后。

## 3. 验证（可复跑）

| 项 | 结果 | 复跑方式 |
|---|---|---|
| 召回 | 23 条题面 × 32 字滑窗 = 136/136 命中 | 见 §5 脚本 |
| 误报 | 现存 2025 个知识文件（`data/methods/*/METHOD.md` + `experiences/**/*.md`）blocked = 0 | 同上 |
| CLI | `--selfcheck` rc=0（23 tasks）；`--text` 含 task_id rc=2，且输出只含 id | `python3 evals/heldout/v1/filter.py --selfcheck` |
| 写侧拒绝 | alias / freshness_ref / note 三条旁路均抛错，磁盘无 task_id | 见单测 |
| 读侧丢弃 | `recent_issue` / `freshness_refs` / `scenario` / 嵌套 dict 内嵌 id 均被丢弃计数 | 见单测 |
| 单测 | `tests/unit/test_heldout_guard.py` 107 passed（含负例） | `.venv/bin/python -m pytest tests/unit/ -q -k heldout` |
| 回归 | method_learning / experience_library / memory_extract / introspection / 两个 durability = 167 passed | 同上文件列表 |
| 静态 | ruff 与 pyright 对本批改动 0 新诊断 | `scripts/check_static_diagnostics.py --tool ruff\|pyright` |

本批改动经过 **三轮独立代码审核**（glm-5.3，只读子代理）：第一轮 1×P1 + 1×P2、第二轮 2×P1（模型可达旁路）、
第三轮 PASS（P0=0，P1=0，剩 3 个当前不可达的 P2）。第二轮的两条 P1 有真实复现（持久化了 task_id），是"审核真的在
对抗"的证据，而不是形式盖章。

## 4. 已知边界（明确不做 / 做不到）

1. **不给 `solution.md` 造探针**：代码片段 24 字重合率太高会误报；且 §2 规定 solution 目录在改进期不进任何索引，
   实际泄漏路径要先有人把它抄出来。检测面 = 题面 + task_id。
2. **题面 >144 字时**探针按 16 个等距抽样，窗口间距可能 >8 字 → 32 字裸引用有漏检可能。当前 23 条题面正文 69–104 字，
   不触发；新增题目若更长需重跑 §5 召回测试。
3. **读侧丢弃计数对模型不可见**：`_last_heldout_filter` 只有进程内消费者（测试），没有进 `search_records` 回执。
   取舍理由：把 dropped 计数发给模型等于告诉它"held-out 存在"，收益低于风险。
4. **held-out 跑批里守卫会拒绝写入**：像 `no_trivial_memory` 这类"本不该写"的判定，可能因为"写了但被拒"而平凡通过。
   解读 held-out 结果时必须单独看这几条的轨迹，不能只看 verdict。
5. 三个未接线写路径（`update_status` 等单键 RMW）当前**无外部调用方**，属防御性缺口（P2），未接守卫。

## 5. 复跑脚本（召回 / 误报）

```bash
PYTHONPATH=src .venv/bin/python -c "import glob,pathlib,collections; from llm_loop.knowledge import heldout_guard as hg; paths=glob.glob('data/methods/*/METHOD.md')+glob.glob('experiences/**/*.md',recursive=True); print(collections.Counter(hg.check_text(pathlib.Path(p).read_text(encoding='utf-8',errors='replace'))['status'] for p in paths))"
```

召回把上面换成对 23 条题面做 32 字/步长 10 的滑窗，逐片段 `check_text`，统计 blocked 比例（应为 1.0）。

## 6. 仍未闭合（下一步，按依赖排序）

1. **eval 知识库状态显式化（E1'，2026-10-25 已落地）**：本节旧前提（"实际读写生产知识库"）已被实测推翻——
   eval 的 Settings 是直构（`run_eval._settings`），factory 对直构 Settings 的路径解析**不读 os.environ**
   （`factory.py:1642` 只用 Settings 字段拼 env dict），知识库本就落在每个样本的临时目录。真实缺口是：
   **每个样本的知识库是空目录**，与生产配置（~1408 method 卡 / ~626 experience 文件）不同质 → Δ 不可归因。
   现状：`scripts/run_eval.py --knowledge-store {empty,snapshot}`（默认 `empty`=历史零知识基线；`snapshot`=
   生产库深拷贝到 run 级快照，**每样本再独立拷贝一份**：写入不回流生产、不跨样本共享）；
   注入点 `settings._extra["runtime_paths"]`（`factory.py:1641` authoritative 分支，`data_dir` 显式覆盖为样本
   tmp/data，防 session/memory/向量缓存跨样本共享）；证据行进报告 meta `knowledge_store`。
   `production` 模式已删除（名不副实 + 可写指针指向生产的脚枪）。
   测试：`tests/scripts/test_run_eval_knowledge_store.py`（含 build_engine 端到端用例）。
2. **held-out 首跑**：`evals/heldout/v1/scenarios_heldout_v1.json` 每场景 pin `max_iterations=12`，产品默认 500；
   跑批必须用 `--budget-profile product --ignore-scenario-pins`（已是 `scripts/run_eval.py` 的能力），
   否则 Δpass@1 不可迁移。
3. **知识池质量**：`data/methods` 1408 张卡里 candidate 1354、带 qualification 68、带 freshness 10；
   "candidate 与 active 等价"是设计（不是权限闸门），真正的风险是 96% 未资格化卡片主导发现。改检索策略须走 A/B，不能直接改默认。
