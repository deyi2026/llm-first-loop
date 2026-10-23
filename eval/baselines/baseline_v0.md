# baseline_v0 — Terminal-Bench v2 全量基线（归因后口径）

> 版本：v0.1 ｜ 生成日期：2026-10-23 ｜ 关联计划：`docs/EVAL-PLAN-LFL-20261023.md`
> 运行目录：`eval/results/baseline_v0_terminus2_glm53_full/2026-10-14__20-23-44/`
> 运行日志：`eval/logs/baseline_v0_full.log`
> 复算脚本：`eval/rules/domain_baseline.py`（域内）｜ 本文件归因可由下方「复算命令」重放

## 1. 运行规格

| 项 | 值 | 来源 |
|---|---|---|
| 数据集 | Terminal-Bench（`terminal-bench-core` **0.1.1**） | `run_metadata.json:dataset_name/dataset_version` |
| Agent harness | **terminus-2** | `run_metadata.json:agent_name` |
| 模型 | **glm-5.3** | `run_metadata.json` |
| 任务数（dataset） | **80** | `len(run_metadata.json:task_ids)` |
| 任务目录（落盘） | **80** | 目录计数 |
| 判定条目（results.json） | **79** | `len(results)` |
| 未判定 | **1**（`path-tracing`） | 目录存在但 results.json 无该条目 |
| `no_rebuild` / `cleanup` | `True` / `True` | `run_metadata.json` |
| 平台 | macOS arm64（`Darwin 25.3.0`），Docker 27.3.1 | 实测 |

## 2. 归因后口径（**唯一可对外口径**）

原始 `accuracy` 字段为 **7/79 = 8.86%**。但该数字**混入了 52 例基础设施失败**，直接用于能力比较是错的。

### 2.1 失败归因表（79 条判定全量归因，无剩余）

| 分组 | n | resolved | 类别 | 可判能力？ |
|---|---|---|---|---|
| `RESOLVED` | **7** | 7 | 真正解决 | ✅ |
| `A_docker_build_failed` | **27** | 0 | 镜像构建失败 → `Command '['docker', ...]'` 返回非零 | ❌ 基础设施 |
| `B_errno24_too_many_open_files` | **16** | 0 | `[Errno 24] Too many open files` | ❌ 基础设施 |
| `C_llm_api_5xx` | **9** | 0 | **残差归因**：既无 A 也无 B，且全局日志存在 5xx 错误块（LiteLLM `RetryError`/`InternalServerError`）。⚠️ 5xx 块**不逐任务绑定**（仅约半数上下文带 task_id），故为排除法推出，证据等级弱于 A/B | ❌ 模型服务侧 |
| `D_test_timeout` | **9** | 0 | 测试命令超时 | ⚠️ agent 侧 |
| `D_parse_error` | **5** | 0 | 答案解析失败 | ⚠️ agent 侧 |
| `D_unset` | **4** | 0 | 未设置判定（`is_resolved=False`） | ⚠️ agent 侧 |
| `D_agent_timeout` | **2** | 0 | agent 自身超时（360s） | ⚠️ agent 侧 |
| **合计** | **79** | 7 | | |

**基础设施类合计 52 例（27+16+9）= 失败总数的 72.2%（52/72）** → 超过 P0 出口判据的 ≤10% 门槛，**该 run 不得用于任何模型能力比较**。

**稳健性论证（剔除证据等级较弱的 C 组）**：即使把 9 例残差归因的 C 组全部剔除，仅 A+B 两类确定性判据也已达 **43/72 = 59.7%** 的失败占比（>30% 门槛）→ **"该基线不可用"的结论不依赖 C 组**。归因器 `eval/rules/attribute.py` 自动输出该 `robustness` 字段。

### 2.2 两个必须并列声明的口径

| 口径 | 分母 | 分子 | 结果 | 用途 |
|---|---|---|---|---|
| **原始口径** | 79 | 7 | **8.86%** | 仅描述"这次 run 跑成了什么样" |
| **agent 可比集口径** | 27（79−52 基础设施类） | 7 | **25.93%** | 仅描述"在 agent 真正跑起来的 27 题上" |

> ⚠️ **25.93% 同样不可外推**：n=27、**Wilson 95% CI = 13.2%–44.7%**（区间宽达 31.5pp），且题目为 agent 自选子集（被环境失败"幸存"的那批通常更简单），存在**幸存者偏差**。禁止以"25.93% 是 LFL 的 Terminal-Bench 能力"对外表述。
> 📌 **禁止只报单一数字**：任何对外表述必须同时给出两个口径并标注基础设施占比。

### 2.3 `failure_mode` 字段的坑（实测）

`failure_mode` 对**已解决任务也被填充**：`git-workflow-hack` / `conda-env-conflict-resolution` / `reshard-c4-data` 三例 `is_resolved=True` 但 `failure_mode="agent_timeout"`。→ **统计失败模式时必须先按 `is_resolved` 切分**，不能直接对 `failure_mode` 做计数。

## 3. 三个必须记录的字段事实

1. **52 例基础设施失败的时间戳与 token 全为 `null`**（`started_at`/`ended_at`/`total_input_tokens`）→ 这是识别"根本没跑起来"的**零成本信号**，无需解析日志即可先做一轮过滤。
2. **79 条中仅 18 条有非零 `total_input_tokens`** → 该 run 的 token 统计**不可用于成本核算**（D-8 成本纪律在此 run 上不可满足）。
3. **`path-tracing` 未判定**：任务目录存在但 `results.json` 无条目；日志显示其属 `Harness execution failed … [Errno 24]` 一类 → 归入 B 组（基础设施），**不是"未归因"**。

## 4. 重跑前置条件（复跑前必须全部满足）

| # | 条件 | 当前状态 | 验证命令 |
|---|---|---|---|
| 1 | Docker build 全部成功 | ❌ 27 例失败 | 逐任务 `docker compose build` |
| 2 | 文件句柄充足（Errno 24） | ❌ 16 例失败 | `ulimit -n` 需远高于默认值；Docker Desktop 侧同步放开 |
| 3 | 模型 API 稳定（无 5xx） | ❌ 9 例失败 | 观察 `LiteLLM.ERROR` 计数为 0 |
| 4 | 汇总层只统计 `is_resolved` | ✅ 已按此口径 | `results.json` 的 `is_resolved` 字段 |

**重跑后出口判据**：基础设施失败占比 ≤10%（当前 72.2%）；未判定任务数 = 0（当前 1）。

## 5. 复算命令

```bash
# 归因计数（可复算：按 failure_mode + is_resolved 交叉统计）
uv run --no-sync python - <<'EOF'
import json, re, collections
R='eval/results/baseline_v0_terminus2_glm53_full/2026-10-14__20-23-44'
log=open('eval/logs/baseline_v0_full.log',errors='replace').read()
res=json.load(open(f'{R}/results.json'))['results']
build=set(re.findall(r"Harness execution failed for \S*/([A-Za-z0-9._-]+): Command '\['docker'", log))
em24=set(re.findall(r"Harness execution failed for \S*/([A-Za-z0-9._-]+): \[Errno 24\]", log))
g=collections.Counter()
for r in res:
    t,f=r['task_id'],r['failure_mode']
    if f=='unknown_agent_error':
        g['A_docker_build' if t in build else ('B_errno24' if t in em24 else 'C_llm_5xx')]+=1
    elif r['is_resolved']: g['RESOLVED']+=1
    else: g['D_'+f]+=1
print(dict(g), 'total=', sum(g.values()))
EOF
```

## 6. 已知任务清单（供重跑与排障）

<details>
<summary>A_docker_build_failed（27）</summary>

`blind-maze-explorer-5x5`, `blind-maze-explorer-algorithm.hard`, `configure-git-webserver`, `count-dataset-tokens`, `crack-7z-hash.easy`, `cron-broken-network`, `decommissioning-service-with-sensitive-data`, `eval-mteb`, `eval-mteb.hard`, `fix-pandas-version`, `get-bitcoin-nodes`, `git-multibranch`, `incompatible-python-fasttext`, `incompatible-python-fasttext.base_with_hint`, `oom`, `path-tracing-reverse`, `processing-pipeline`, `pytorch-model-cli.hard`, `qemu-alpine-ssh`, `qemu-startup`, `raman-fitting.easy`, `run-pdp11-code`, `simple-sheets-put`, `simple-web-scraper`, `swe-bench-astropy-1`, `swe-bench-astropy-2`, `train-fasttext`

</details>

<details>
<summary>B_errno24_too_many_open_files（16）</summary>

`build-tcc-qemu`, `csv-to-parquet`, `extract-safely`, `fix-git`, `gpt2-codegolf`, `intrusion-detection`, `modernize-fortran-build`, `new-encrypt-command`, `openssl-selfsigned-cert`, `polyglot-rust-c`, `raman-fitting`, `sanitize-git-repo.hard`, `sqlite-db-truncate`, `tmux-advanced-workflow`, `vim-terminal-task`, `write-compressor`

</details>

<details>
<summary>C_llm_api_5xx（9）</summary>

`chess-best-move`, `crack-7z-hash`, `hello-world`, `jupyter-notebook-server`, `password-recovery`, `polyglot-c-py`, `prove-plus-comm`, `solana-data`, `sqlite-with-gcov`

</details>

<details>
<summary>D 组（agent 侧，20）</summary>

- `D_test_timeout`（9）：`blind-maze-explorer-algorithm`, `crack-7z-hash.hard`, `create-bucket`, `fix-permissions`, `grid-pattern-transform`, `play-zork`, `pytorch-model-cli.easy`, `swe-bench-fsspec`, `swe-bench-langcodes`
- `D_parse_error`（5）：`build-linux-kernel-qemu`, `download-youtube`, `extract-moves-from-video`, `pytorch-model-cli`, `security-vulhub-minio`
- `D_unset`（4）：`fibonacci-server`, `nginx-request-logging`, `sanitize-git-repo`, `super-benchmark-upet`
- `D_agent_timeout`（2）：`build-initramfs-qemu`, `hf-model-inference`

</details>

## 7. 本文件的证据等级

**B 级（可复算的观测）** —— 归因表与两个口径可由 §5 命令在本机复算；样本为**单次历史 run**，非受控实验；**不可用于任何跨模型/跨 harness 的能力声明**。
