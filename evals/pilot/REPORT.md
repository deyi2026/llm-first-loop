# Local Agent Pilot 评测报告（Cline + Deep Agents vs LFL）

日期：2026-09-12 · 执行人：LFL（goal GOAL-20260912-f4655ad5 T4）

## 1. 目的与口径

在**同一本地 Ornith-1.5-35B-A3B-MLX 模型服务**（LM Studio, 127.0.0.1:8901）上，对比三个 agent harness 完成同一组 12 个小型 coding 任务的表现：

- **lfl**：本仓库 llm-first-loop（plan 模式，默认模型）
- **da**：langchain Deep Agents（`dsh_task` 委派，同模型经 OpenAI 兼容端点）
- **cline**：Cline headless（`cline --task --exit`，同模型）

每任务 ×3 次重复，判定均为**程序化验收**（文件存在/内容匹配/命令输出匹配），无人工评分。

## 2. 任务集（12）

均为小型、程序化可判定的任务，每 run 独立 tmp 工作区：

| ID | 任务 | 验收 |
|----|------|------|
| t01_read_first_line | 读 probe.txt 第一行原文写入 answer.txt | 内容 == `PYTHQN-MARKER-L1`（含拼写陷阱） |
| t02_retry_transient | 运行 gen.py；首次必失败，需诊断后重试 | result.json == {ok:true, n:42} |
| t03_build_module | 写 fib.py + test_fib.py 并跑 unittest | fib(10)=55, fib(0)=0，测试退出码 0 |
| t04_fix_bug | 修 broken.py 的 median 缺陷（不许改测试） | 3 个既有测试通过 |
| t05_multi_file_sum | 读 a/b/c.txt 全部整数求和 | total.txt == 41 |
| t06_log_count | 数 app.log 中 ERROR 级别行数 | errcount.txt == 3 |
| t07_json_flatten | 展开 in.json 的 data.items 各 name | names.txt == alpha/beta/gamma（3 行） |
| t08_resume_todo | 按 README-TASK.md 补全 half_done.py 的 TODO | `python3 half_done.py` 打印 OK |
| t09_big_file_line | 取 big.txt（2500 行）第 2024 行 | line2024.txt == L2024 |
| t10_fs_invariant | 建 A.txt=keep、B.txt=drop 后删 B.txt | A.txt 存在且 == keep，B.txt 不存在 |
| t11_env_facts | 用命令实取 whoami/pwd 写 facts.json | 值与真实回执一致（事实纪律探针） |
| t12_interrupt_resume | 三阶段建 stage{1,2,3}.txt + mark.py 标记；第 25s 强杀一次后续接 | marks.json == [p1,p2,p3]，三文件内容 one/two/three |

任务定义源码：`evals/pilot/tasks.py`（prompt/setup/verify 全部确定化，无网络依赖）。

注：t11 初版 prompt 未明确要求先 `cd` 工作区，首跑记录了错误 cwd；修正 prompt（明确 `cd {ws}` 后再运行）后三个 harness 均以修正版计入统计（分析脚本按 (agent,task,run) 取最新记录去重）。

## 3. 结果

数据：`results.jsonl`（108 条，按 (agent,task,run) 取最新 ts 去重）；分析脚本 `analyze.py`。

### 3.1 通过率

| agent | 通过 | 总通过率 | Wilson 95% CI |
|-------|------|----------|----------------|
| lfl | 35/36 | **97.2%** | [0.86, 1.00] |
| da (Deep Agents) | 36/36 | **100.0%** | [0.90, 1.00] |
| cline (headless) | 33/36 | **91.7%** | [0.78, 0.97] |

三组 CI 大面积重叠：pilot 样本量下**无法区分**三者真实成功率差异，结论只对失败模式负责。

任务级矩阵（pass/runs）：除下述 3 个失败 run 外全部 3/3。

- t06_log_count：lfl r2 失败——agent 7 轮内数对了 ERROR 数但**未写 errcount.txt**（工作区无任何输出文件），完成纪律缺失。
- t12_interrupt_resume：cline r1-r3 全失败——25s 强杀后再调用 headless cline 时**新建了工作区**（如 r1 的 `0ec65d`→`bdbaed`），未续接原 ws；模型在新 ws 实际完成了全部阶段（marks.json == [p1,p2,p3] 内容正确），但验收在原 ws 执行 → FileNotFoundError。属于 harness 续接语义边界，非模型任务能力失败。

### 3.2 时长（秒/任务，中位/均值/p90）

| agent | median | mean | p90 |
|-------|--------|------|-----|
| lfl | 36 | 47 | 83 |
| da | 42 | 68 | 140 |
| cline | 41 | 50 | 83 |

lfl 与 cline 时长分布接近；da 均值/p90 明显更长（长尾来自复杂任务与重试）。

### 3.3 解读（pilot 级，样本量小）

1. **同一模型、小任务集上三者任务成功率接近**（92–100%），差距主要体现在失败模式而非成功率。
2. 失败模式区分度好：lfl 的失败是"算对没落盘"（完成纪律），cline 的失败集中在"进程外续接"（headless 再入语义），da 本次无失败但 p90 时长最长。
3. t12（中断-续接）对 harness 续接语义敏感：lfl 原生 session resume 3/3，da 以新会话续接同 cwd 3/3，cline headless 新 ws 0/3——评测项测到的是 harness 能力边界而非模型能力。

## 4. 局限

- 单机单模型、12 小任务、3 次重复；统计功效有限，结论仅作 pilot 参考。
- lfl 为本仓库开发中版本，存在自评偏置风险；判定脚本对所有 harness 一致。
- da/cline 为 headless 模式，与交互式使用体验可能有差异。
