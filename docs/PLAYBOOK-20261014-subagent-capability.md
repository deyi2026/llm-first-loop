# 子代理能力配置 Playbook（v1 · 2026-10-14）

## 目的与适用场景

用 spawn_subagent 委派子任务时，把能力**一次配对**：工具列全、能力声明齐、执行权约束心里有数。避免三类浪费——工具面没给（不可见/拒绝）、能力缺口（中途断）、effect 权威被拒（lease/generation 任一不满足即拒，见③）。

## 三层机制速查（源码核实）

| 层 | 机制 | 锚点 | 卡点表现 | 处置 |
|---|---|---|---|---|
| ① 工具面 | `requires.tools` 是程序级强制白名单：声明即截断发现面+执行面，声明外调用确定性拒绝；**不声明则继承父执行域**（授权只降不升） | spawn_subagent.py:25 | 工具不可见；"声明外调用被运行时确定性拒绝" | spawn 前把任务真正需要的工具列全 |
| ② 能力声明 | `requires.network / fs / session_continuity` 在 child 启动前比对能力矩阵，缺口 fail-fast 拒绝（带替代面提示） | 能力矩阵比对 | spawn 直接被拒 | 需要网络/文件读写就在 spawn 时声明；启动前拒绝好过跑到一半失败 |
| ③ 执行权 | effect 类工具（execute_command / edit_file / dsh_task / workflow）每个提交窗口过两道权威：① lease fence（lease 在 + coordinator 在 + 磁盘 current，renew 失败 sticky 后 fail closed）；② run_generation_authority（binding 带父 run 代际查**子会话**注册表 → 必然失配拒绝） | runner.py:797,799,2315 / journal.py:437-449 / session.py:1242 | "effect authority 丢失 run lease fenced"（⚠️ 文案不分来源，generation 拒也报 lease fenced） | 2026-10-14 已修复根因②（子代理 binding 代际隔离）；修复前子代理 execute_command 自上线起 100% 被拒（26 会话 0 成功），修复后子代理可执行 effect，仍受 lease fence 正常约束 |

**注意**：2026-10-14 前的"fenced 是设计"判断已被推翻——那是 generation 继承缺陷（见实测记录 v2），修复后子代理 effect 工具可用。E4 白名单本身仍是设计：只读任务别硬塞 effect 工具。

## 按任务类型的配置模板

| 类型 | requires 配置 | 备注 |
|---|---|---|
| 调研型 | `tools=[web_search, web_fetch, read_file]` + `network=true` | 不需要 fs 就不声明，授权只降不升 |
| 代码审查型 | `tools=[read_file, search_files, inspect_code]` + `fs=true` | 只读是设计，别硬塞 shell |
| 验证执行型 | `tools=[read_file, search_files, inspect_code, execute_command]` + `fs=true` | 2026-10-14 修复后 execute_command 可用（根因见实测记录 v2）；仍建议关键验证结果以回执原文复核 |

## 七条清单（spawn 前过一遍）

1. **工具列全**——按任务类型配模板；漏列=子代理看得见任务干不了活。
2. **能力声明防中途断**——需要网络/文件读写就在 spawn 时声明。
3. **context 精准投喂**——child 没有父全量历史，只传路径、判定标准、证据锚点。工具再全，缺背景发挥不出来。
4. **acceptance 逐项可自检**——倒逼收敛，结果更可靠。
5. **模型用完全限定名** `glm/glm-5.3`——裸名双 provider 匹配会 refused；不指定走默认亦可。
6. **effect 工具可用性看版本**——2026-10-14 前的部署子代理 execute_command 100% 被拒（generation 继承缺陷，非 lease、非任务形态）；修复（commit 见 v2 记录）后可用。判断当前环境是否已修：看子代理回执原文是否有 unauthorized。
7. **中途纠偏**——`agent_message` steer；终止后 `agent_followup` 续话（每 child ≤2 次 / 父 ≤4 次 / 15min 窗口）。

## 验证纪律

- 子代理能力是否发挥，**以工具回执/事件日志为准，勿信自我报告**（EXPERIENCE-20261012）。
- spawn 回执的 `tool_scope` 行是第①层生效的直接证据。
- effect 工具通不通，看子代理回执原文，不是看它声称"成功"。

## 实测记录

### v1 验证（2026-10-14 · child=subagent_763a233964cb）

**spawn 配置**：`tools=[read_file, search_files, inspect_code, execute_command]` + `fs=true`（network 未声明）+ `inherit=false`；7 轮 16 次调用结算。

| 层 | 结果 | 证据 |
|---|---|---|
| ① 工具面 | ✅ 通 | spawn 回执 `tool_scope` 四工具全进白名单；子代理对白名单外工具（search_records）如实报"会话无此工具" |
| ② 能力面 | ✅ 通 | fs=true 下真实读仓库（STACK.md 99 行、pyproject.toml 74 行、requirements.txt 等）：read_file 3✅ / search_files 7✅ / inspect_code 2✅，0 失败 |
| ③ 执行权 | ❌ 全程 fenced | execute_command 两次 unauthorized，原样错误：`effect authority 丢失（run lease fenced），命令拒绝执行: git log -1 --oneline`；与上轮审查子代理 8 次 unauthorized 同模式，**两次独立 spawn 复现** |

**结论**：任务小、运行正常（child_state=completed，7 轮跑完）与 fence 无关——子代理侧 effect 层在当前环境下基本不可用，**不是"任务切小/时限合理"能防的**。需要跑命令的验证在设计任务时就留给父会话。

**附带观察**：
- 子代理按 acceptance 自检表现良好：发现任务前提偏差（STACK.md 实为三层权威边界治理文档而非技术栈清单）后按替代口径完成核验，如实区分"已调用成功"与"未尝试"，无虚构。
- inspect_code 目录级返回空：**已排查，非缺陷**。事件日志还原子代理原始参数 `{"depth": 1, "path": "src"}`——depth=1 只扫 root 直接子层，src 下仅 llm_loop/ 目录 → 空。父会话同参数默认 depth=2 返回 8 文件。v1 判为"疑似缺陷"是当时回执只有 args_sha256 无参数明文所致。改进建议（可选）：空结果提示带 depth 语义，防误判。

### v2 深挖与修复（2026-10-14 下午 · 根因闭环）

**排查结论**（证据链：data/fleet/state.json 磁盘真相 + data/event_logs/subagent_*.jsonl 26 会话统计 + journal/session/runner 源码）：

1. **fenced 根因不是 lease**：ws-87（763a）lease 链完美（acquire 16:49:26 → renew 全成功续至 17:06:23 → 16:51:45 settled/completed）；87 个 lease 全 settled 无 superseded；测试真实 store 链路全绿。
2. **真根因**：journal `effect_mutation_authority` 在 lease fence 之后还有一道 `run_generation_authority`；spawn worker 线程 `copy_context()` 继承**父 run 的 current_run_generation**，binding 带父代去查**子会话**注册表（子 sid 从未注册 → `"" != 父代`）→ 全部 effect 工具拒绝，而 execute_command 文案写死 "run lease fenced" 造成误导。测试全绿的原因：单测路径 generation 默认 ""（legacy 放行），从未覆盖"父代非空"的生产形态。
3. **影响面**：2026-10-12 18:59 起 26 个子代理会话 execute_command 0 成功 / 19+ 次 unauthorized，全部 round 1-2 即拒——确定性缺陷，非竞态。
4. **修复**：runner.py `_execute_subagent` 工具执行窗口隔离 `current_run_generation.set("")`（子代理 effect 权威回归 R1 lease fence 单一来源）+ red→green 复现测试 `tests/unit/test_subagent_effect_generation_isolation.py`（修复前 `allowed=False` 精确复现生产形态）。回归子集 315 passed；全量 7508 passed / 108 skipped / 1 failed（test_static_diagnostic_gate 预先存在失败，stash 干净树复现同败，与本次修复无关）。

**insight**：unauthorized 文案与真实拒绝原因错位是本次排查最大成本——"run lease fenced" 文案让排查在 lease 链路上空转，磁盘真相才纠偏。权威分层（lease / generation）的拒绝消息应区分来源。
