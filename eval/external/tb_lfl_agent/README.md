# Terminal-Bench 适配器：LFL 作为 TB agent（P4）

## 现状

`lfl_agent.py` **已在真实 TB 容器上跑通**（2026-10-23 实测，TB 1.0.2 / terminal-bench
pip 0.2.18，见下方「实测结果」）。P4 冒烟完成 1 题（`crack-7z-hash`，1/1 resolved）。
本文档如实登记：已完成什么、未完成什么、以及结论的适用边界。

## 实测结果（2026-10-23）

| 项 | 值 |
|---|---|
| 任务 | `crack-7z-hash`（terminal-bench-core==0.1.1，80 题集） |
| 判定 | **Resolved 1 / Unresolved 0，Accuracy 100%** |
| 测试判定 | `test_outputs.py::test_solution_file` + `::test_solution_content` → 2 passed |
| 真实产出 | 容器内解出 7z 密码 `honeybear`，写入 `/app/solution.txt` |
| token | input 175,177 / output 5,072 |
| agent 耗时 | 2 分 14 秒（多轮容器交互，非单次调用） |
| 证据 | `runs/2026-10-23__12-46-48/`（`sessions/agent.log`、`panes/post-agent.txt`、`sessions/tests.log`） |

**这是 1 题冒烟，不是基准结论**：n=1 无统计意义，不能对外表述为"LFL 在 TB 上的准确率"。

## ⚠️ 第二题实测暴露的 TB harness 时序竞态（比 adapter 更重要的坑）

`configure-git-webserver` 实跑（2026-10-23 13:09）：agent **在容器里把活干完了**
（`git push` 成功、`curl` 返回 `hello world`、最终 ref 校验通过），
`sessions/tests.log` 里 pytest 也是 **1 passed in 20.92s**，
但 TB 判为 **`failure_mode=parse_error`、`resolved=None`、tokens 0/0**。

**根因链**（不是 adapter 缺陷）：
1. agent 超过默认 **360s** 全局超时 → TB 触发 agent timeout 分支；
2. TB 采样 `panes/post-test.txt` 时**测试还没跑完**（该题测试耗时 20.92s；
   对比第 1 题 `crack-7z-hash` 测试 0.00s，post-test pane 完整含 summary）；
3. `pytest_parser.parse()` 要求 pane 里有 `short test summary info` 段
   （`terminal_bench/parsers/pytest_parser.py:83-93`，缺失即 `raise ValueError`）；
4. → harness 记 `FailureMode.PARSE_ERROR`（`harness/harness.py:611`），
   **任务实际已解出但被判失败**。

**判别方法**（下次遇到别误判成 agent 不行）：
- `sessions/tests.log` 有 `N passed` 而 `panes/post-test.txt` 无
  `short test summary info` → 是这个竞态，**不是**能力失败；
- `sessions/lfl_agent_error.txt` 存在 → 才是 adapter 侧异常。

**规避**：给足超时（CLI 有 `--global-agent-timeout-sec` / `--global-test-timeout-sec`，
默认 360s 对复杂题偏紧）：

```bash
/tmp/tb13/bin/tb run --dataset terminal-bench-core==0.1.1 \
  --task-id <task> --agent-import-path lfl_agent:LflAgent \
  --n-concurrent 1 --n-attempts 1 --no-livestream \
  --global-agent-timeout-sec 1200 --global-test-timeout-sec 600
```

**结论口径纪律**：TB 报的 `parse_error` 必须回查 `tests.log` 才能定性，
不得直接计入 agent 失败率。

## 版本事实（引用本仓库结论时必须同时说明）

- 本次实跑用 **terminal-bench pip 0.2.18（TB 1.x）**。
- 上游已发布 **Terminal-Bench 2.0**，官方 harness 换成 **harbor**
  （`harbor run --dataset terminal-bench@2.0 --agent <name>`），
  官方公告 "New users should check out harbor, our new framework"。
- **harbor/TB2.0 的 agent 契约与 1.x 不兼容**：agent 运行在 environment 容器内，
  契约是 `BaseEnvironment` + `AgentContext` + 数值 reward（`/logs/verifier/reward.txt`），
  而 1.x 是宿主机侧 `BaseAgent.perform_task(instruction, session, logging_dir)`。
- → 本适配器**只对 TB 1.x 成立**；迁移到 harbor/TB2.0 需重写 agent 契约（未做）。
- TB 1.x 的 `tb` CLI 在 **Python 3.14 下崩溃**（typer 解析 `list[str] | None` 注解失败），
  实跑用 Python 3.13（项目 venv 本身就是 3.13.13）。

## 已完成

1. **TB agent 契约对齐**（对照 `terminal_bench/agents/base_agent.py` 实测，0.2.18）：
   - `name()` → `"lfl"`
   - `perform_task(instruction, session, logging_dir)` → 返回 `AgentResult`
     ⚠️ **参数名必须是 `instruction`/`session`/`logging_dir`**：harness 用**关键字**调用
     （`harness/harness.py:625`），写成 `task`/`tmux_session` 会 TypeError（首轮实跑实测）。
   - `AgentResult` **没有** `agent_output` 字段 → agent 最终说明改由 `timestamped_markers` 携带
   - `FailureMode` 枚举实测为 `UNSET/NONE/UNKNOWN/TEST_TIMEOUT/AGENT_TIMEOUT/UNKNOWN_AGENT_ERROR/PARSE_ERROR/FATAL_LLM_PARSE_ERROR/CONTEXT_LENGTH_EXCEEDED/OUTPUT_LENGTH_EXCEEDED/AGENT_INSTALLATION_FAILED`（**无** `FAILURE_MODE_SETUP`/`_AGENT`/`_PARSE`）
2. **受限工具集**（方案 C）：`tb_shell`（发命令进容器 + 回读输出）、`tb_read`（回读屏幕）
3. **引擎构建**：`build_engine(settings)` 装配全套工具后，`registry.unregister()` 逐个注销默认工具，只留两项
4. **失败模式映射**：agent 自身异常 → `UNKNOWN_AGENT_ERROR`（显式归因）；正常跑完 → `NONE`（由 TB 另行跑测试判定）
5. **ingress 通道凭据**（2026-10-23 实测补）：`engine.run(..., ingress=issue_ingress("cli"))`
   —— 缺省会触发 LFL 的通道白名单拒绝（`leak.channel_denied`），agent 收到隔离提示而非任务响应。
   `issue_ingress` 是正式签发入口（非 `issue_test_ingress` 测试后门）。
6. **错误可审计**（2026-10-23 实测补）：agent 侧异常落盘到 TB 的 `logging_dir/lfl_agent_error.txt`
   （含 traceback）。此前异常只进 `AgentResult.markers`、TB 不回显 → 只能看到
   `unknown_agent_error` 无法归因。

## 实跑中修正的契约不符（全部由实跑发现，静态检查发现不了）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | `parse_error` | `perform_task` 参数名与 harness 关键字调用不匹配 | 改为 `instruction/session/logging_dir` |
| 2 | `parse_error` | 用了 `Settings` 但未 import | `from llm_loop.config import Settings` |
| 3 | `unknown_agent_error` | `Settings` 必填 `llm_api_key`/`llm_base_url`/`llm_model` | 三件套齐备；base_url 走模型注册表（`registry.client_params`）解析 |
| 4 | `unknown_agent_error` | TB 侧 venv 缺 `pycryptodome`（LFL task_budget 依赖 `Crypto`） | TB venv 装 `pycryptodome` |
| 5 | answer = "[写入被拒] …" | 未签发 ingress 凭据 → 通道白名单拒绝 | `engine.run(..., ingress=issue_ingress("cli"))` |
| 6 | 任务提示为空 | `getattr(task, "instruction", "")` 对字符串恒为空 | 兼容 str / 对象两种形态 |

> 注：4 与 5 属于**环境/装配前置**，不是 adapter 代码缺陷；复现步骤见下「重跑前置条件」。

## 适配改动量（结论适用边界，必须随数字一起引用）

| 项 | 原生 LFL | 本适配 |
|---|---|---|
| 工具集 | 全量（含 read_file/execute_command/memory/evidence/...） | **仅 2 项**（`tb_shell`/`tb_read`） |
| 可见世界 | 宿主工作区 + 记忆库 + 证据库 | **仅任务容器** |
| 入口 | Web/Feishu/CLI | TB harness（`--agent-import-path`） |

→ **本适配不是"原封不动的 LFL 跑 TB"**。结论只对"受限终端工具集下的 LFL"成立。
→ 报告时必须写明：工具集受限、宿主不可见、因此**不可**与"其他 agent 全工具"横向比较。

## 未完成（P4 剩余待办）

- [x] `tb run --agent-import-path lfl_agent:LflAgent --task-id crack-7z-hash` 真实跑 1 题
      → 2026-10-23 实测 1/1 resolved（见「实测结果」）
- [ ] 容器内 `T_BENCH_*` 环境变量注入（TB harness 侧）
- [x] macOS `ulimit -n` 从 256 提到 10240 → 本次实跑已用 `ulimit -n 10240` 启动，
      Docker build 正常（P0 归因 A 组的 Errno24 未复现）
- [ ] Docker build 失败的完整复现（27 例 A 组的 stderr 未被 TB 记录）
- [ ] 扩到多样本（当前 n=1，无统计意义）
- [ ] 若要迁移到 TB 2.0/harbor：需重写 agent 契约（见「版本事实」），本适配不通用

## 重跑前置条件（2026-10-23 实跑确认可用）

```bash
# 1) TB 1.x 独立 venv（必须 Python 3.13；3.14 下 tb CLI 崩溃）
uv venv --python 3.13 /tmp/tb13
uv pip install --python /tmp/tb13/bin/python "terminal-bench==0.2.18" pycryptodome
#    pycryptodome 是 LFL task_budget 的依赖（Crypto），缺则 agent 侧 unknown_agent_error

# 2) 数据集（首次）
/tmp/tb13/bin/tb datasets download -d terminal-bench-core==0.1.1

# 3) 运行（实测可用的一行）
ulimit -n 10240
export PYTHONPATH="$PWD/eval/external/tb_lfl_agent"   # 让 tb 找得到 lfl_agent 模块
export MINIMAX_API_KEY=$(grep '^MINIMAX_API_KEY=' .env | cut -d= -f2-)
export LLM_MODEL=minimax/MiniMax-M3.1-Flash
/tmp/tb13/bin/tb run \
  --dataset terminal-bench-core==0.1.1 \
  --task-id crack-7z-hash \
  --agent-import-path lfl_agent:LflAgent \
  --n-concurrent 1 --n-attempts 1 --no-livestream

# 4) 看结果
cat runs/<run-id>/results.json
```

> `--agent-import-path` 传**模块路径**（`module:Class`），不是文件路径；
> 传文件路径会报 "Could not import agent from path"。
> `--agent` 只接受内置枚举（oracle/none/…），自定义 agent 一律用 `--agent-import-path`。

```bash
ulimit -n 10240                 # macOS 默认 256 → Errno24（16 例）
export T_BENCH_TASK_DOCKER_CLIENT_IMAGE=...
export T_BENCH_TASK_DOCKER_CLIENT_CONTAINER_NAME=...
export T_BENCH_TASK_DOCKER_CLIENT_DOCKER_CONFIG=...
export T_BENCH_TASK_DOCKER_CLIENT_CONTAINER_NETWORK=...
```
