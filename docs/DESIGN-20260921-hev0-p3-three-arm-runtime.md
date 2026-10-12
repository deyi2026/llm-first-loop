# DESIGN-20260921 · hev0 P3 方向2：B0/B1 运行时对比口径 v1（**已冻结**）

状态：**冻结执行协议**（2026-09-21T08:50:58+08:00 用户裁决 D-1/D-2/D-3 后生效，见 §9 决议记录）。
冻结后变更须显式修订（新增 D-编号 + 用户确认），不允许静默改条件。本文档不含任何 LLM 行执行。
上游：`evals/harness_evolution_v0/results/hev0-freeze-20260920T220150Z/p1-annotations.md` P2 结论
（anchor A/B 在 reward 与 cost 双维度零判别力；12/12 reward=1.0；t4 k3 单次翻转证明方差主导）。

## 1. 研究问题与可证伪假设

RQ：**LFL core 整体**（loop 引擎 + 76 工具面 + history 管线/压缩 + 记忆/目标/证据栈 + system prompt 契约）
相对"同模型裸循环"是否带来 reward 或成本增益？

- H1（core 增益）：S2 主消融层存在 B1 > B0 的 reward 差，或 reward 持平时 B1 成本更优。
- H0（可证伪结局）：B0 与 B1 reward 相同且成本相同或更优 → core 增益假设受挫，如实记录。

**臂定义**
| 臂 | 定义 | anchor |
|---|---|---|
| B0 | 裸模型驱动循环（本文 §3，eval 内新实现 b0_driver.py） | 无此概念 |
| B1 | = P1 baseline 臂：完整 LFL 运行时，worker.py 现行路径 | 强制 off（TASK_ANCHOR_PIN_MESSAGES=0 + provider=None） |
| B2 | = P1 candidate 臂 | 默认 on（pins=2） |

B2 在 P3 主域**不重跑**：P1/P2 已证 anchor 在 t4-t8 机械惰性（pins=0）且成本效应在可行 k 下不可裁决
（闭合需 k≥10 ≈ 3.4M tokens）。B2 数据按同 worker sha 从既有冻结行引用。anchor 在压缩域的成本问题
从未在 k≥2 下测过，作为可选模块 M2 单列（§7）。

## 2. 任务分层（以 B0 可比性为唯一准则）

| 层 | 任务 | 依据（今日实测） | 进 P3？ |
|---|---|---|---|
| S2 主消融 | t4, t5, t6 | seed 443/421/0 chars，原始上下文可容纳；判分只依赖物理产物/最终答案；t6 的 12 页源是 workspace 普通文件（`tasks/t6_evidence_paging/workspace/pages/*.txt`），B0 的 read_file 可达 | **B0×B1×k3 = 18 行** |
| S1 结构天花板 | t1, t2, t3 | seed 1,500,516 / 1,500,516 / 2,700,581 chars，远超 provider max_input_tokens=184k → B0 原样注入必然首轮被拒 | **仅 B0×k1 = 3 行**（存在性记录：core 使长前史任务可行；不做效应量） |
| S3 机械依赖 | t7, t8 | 构造性依赖 B0 不具备的机械（记忆/goal 命名空间；subagent） | 排除，B1/B2 侧沿用 P1/P2 既有行 |

对账项 C-1：S1 的 B1 参照行需核对是否存在于 worker sha 143c63d7 冻结；无则各补 k1 共 3 行。

## 3. B0 裸会话定义（钉死）

1. **客户端**：直接复用 `llm_loop.llm.client.LLMClient`，settings 走与 worker.py 相同的 `load_settings()`
   解析路径 → 同活动模型、同 fallback 链、同传输层。实测解析（2026-09-21）：
   `llm_model = cognilocal/qwen3.8-flash-next`，`max_iterations = 500`，fallbacks `glm/glm-5.3-flash, deepseek/deepseek-flash, minimax/MiniMax-M3`。
2. **会话**：单进程单会话，消息序列 = `[system(B0 prompt, 附录A冻结文本)] + [seed history 原样逐条注入，不加任何摘要/加工] + [instruction 序列]`。
   instruction 序列 = instruction.txt + task.json.extra_instructions，与 worker.py 逐字同序。
   无会话存储、无跨轮持久化、无 history 管线——上下文只增不减，溢出即终态。
3. **循环**：`rounds < 500`（= settings.max_iterations 冻结解析值，两臂同值，写入 manifest）内：
   有 tool_calls → 在行 workspace（cwd）执行 → append 结果 → 继续；无 tool_calls → 本条 instruction 结束，
   最后一条 assistant 文本 = final_answer；逐条推进 instruction。provider 拒绝/异常 → 记终态
   （`ctx_overflow` / `provider_error`），不重试，行不判失败（rc=0，reward 由 oracle 按产物判）。
4. **工具面 = 5 个物理原语**：`read_file / edit_file / execute_command / search_files / inspect_code`。
   实现优先**同源复用** llm_loop 内建工具对象（名字/schema/执行语义/硬安全边界 100% 同源）；
   若工具对象运行期耦合引擎 run_context 无法脱离引擎，降级为 eval 内镜像实现，须过 G1 哈希门 + 语义对齐说明。
   排除其余 71 个工具（goal/task/evidence/memory/subagent/browser/web/……）——这是**处理的一部分**，不是缺陷。
5. **判分同构**：与 worker 完全一致——同 oracle 调用、同 final_answer 口径、同 ws_archive 归档、
   rows.jsonl 同 schema（增 `arm="b0"`、`b0_terminal` 字段）。
6. **usage 记账**：每轮从 client 响应直接累计 tokens_in/out/rounds，口径与 LFL `request.usage` 同源。

## 4. 资格门（全部无 LLM，全绿才准进 Stage-A）

- **G1 工具同源**：B0 五工具的 name+parameters JSON 与引擎 registry（实测 76 工具面）对应条目哈希一致。
- **G2 假 client 干跑**：脚本化注入 tool_call → 执行 → 结果回填 → 终止条件，全链路无网络。
- **G3 溢出路径**：t1 seed（1.50M chars）原样注入 → driver 记 `ctx_overflow` 终态，rc=0，不崩溃。
- **G4 判分同构**：B0 行输出喂 oracle 自检（pass/fail 臂均验证）。

## 5. 统计预注册（吸收 P1/P2 教训）

- 主指标 reward（byte-exact oracle）；副指标 rounds、tokens_in。
- S2 每格 k=3 起步；**预注册解读规则：k=3 只做方向性读取 + 符号检验；成本差 <30% 或符号检验不可拒（p>0.125）不下结论**——P2 已实证单次翻转存在（t4 k3 反向）。S2 出现臂间 reward 差 → 补 k=5 再裁决。
- S1 只记存在性（B0 预期确定性溢出 0/3 vs B1 既有表现），不做检验、不计效应量。
- 分阶段：**Stage-A** = S2 B0×B1×k1（6 行）+ G1-G4 全绿 → 才放 **Stage-B**（补至 k3，共 18 行）+ S1 3 行。

## 6. 冻结与 manifest 扩展

- preflight 增字段：`b0_prompt_sha256`、`b0_tool_schemas_sha256`、`b0_round_cap`、**活动模型解析值**。
- **D6（新发现的记录缺陷，须修）**：v4 manifest 的 budgets 只记了 providers.json 的 glm stanza（glm-5.3），
  而实际活动模型是 `cognilocal/qwen3.8-flash-next`（.env LLM_MODEL）。P3 preflight 必须记录
  `load_settings()` 解析出的活动 provider/model + fallback 链，不能只记某 stanza。
- B0 代码进 eval_code_sha256 冻结面；行执行入口 = run_ab.py 按 arm 分发到 worker.py / b0_driver.py。

## 7. 成本预估与可选模块

| 项 | 行数 | tokens_in 预估 | 依据 |
|---|---|---|---|
| S2 B0×B1×k3 | 18 | ~1.2-1.8M | v4/P2 同任务 B1 行 38-134k/行；B0 行预期更低（无 76 工具 schema 注入） |
| S1 B0×k1 | 3 | ≈0 | 首轮请求即被 184k 上限拒绝 |
| C-1 补齐（视对账） | ≤3 | ~0.3M | t1-t3 B1 行重（1.5-2.7M chars 前史） |
| **M2 可选**：t1-t3 × B1×B2 × k3（anchor 压缩域成本问题，从未在 k≥2 测过） | 18 | ~2-4M | 压缩域行重；reward 已知双臂天花板 1.0，只测成本 |

## 8. 混淆边界（诚实声明）

- B0−B1 差异是**复合处理**（机制 + 76→5 工具面 + system prompt），结论只能下到"LFL core 整体"粒度，不可归因单机制。这是有意设计：P3 测整体价值，机制级拆解另立项。
- 5 工具的选择本身是设计自由度（依据 = LFL 物理原语最小集），冻结后不可改。
- B0 prompt 极简（附录 A）；prompt 差异属于处理，不另做控制。

## 9. 用户裁决记录（2026-09-21T08:50:58+08:00，"按建议执行"）

- **D-1 保留 S1 ✅**：3 行近零成本存在性记录保留。理由：把"结构天花板"（1.50M-2.70M chars 物理不可入，
  与策略无关）与"策略缺陷"切开是唯一干净方式；删除成本为正、决策成本为零。
- **D-2 M2 推迟 ✅**：anchor 压缩域成本实验不在本轮跑。理由：M2 结果不改变本轮任何分支；anchor 成本
  形态依赖任务形态，应待方向(a)新任务设计定型后再测。**已记入方向(a)待办**：
  新任务形态定型后评估 anchor 开销形态（若新设计默认开启 anchor 且不可关，则 M2 数据影响新设计，
  必须前置测试）。
- **D-3 原条件确认 ✅，不放水**：Stage-A 放行 = G1-G4 全绿 + S2 k1 六行全部可判分，一字不改。
  单行不可判分 = seed 处于判分边界 = 坏 seed，正确动作是换 seed 或修判分器，不是容忍。
  资格门是机械 smoke test，无裁量空间；跑完再挑 = 资格门失效。

**冻结生效顺序**：D-3/D-1 即刻生效（§4/§5 条件不变）；D-2 记入方向(a)待办清单。

## 9.1 勘误（F1，2026-09-21T15:32:54+08:00 用户裁决 D-11：勘误注记，不回写数据）

- **勘误对象**：§1 臂定义表 B1 行"anchor：强制 off（TASK_ANCHOR_PIN_MESSAGES=0 + provider=None）"。
  终跑（run hev0-p3-20260921T024511Z）B1 臂实际以**引擎默认 anchor ON（pins=2）**运行。
- **证据链**：config.py:825 `env_int("TASK_ANCHOR_PIN_MESSAGES", 2)`（默认 on）；.env 与会话 env 均无该变量；
  worker.py 仅 `arm=="baseline"` 分支强制 off，ARMS_P3.b1 env={} 且 arm="b1" 不触发；t1-t3 b1 行 session
  `history_anchors={"glm":0}`（provider 在压缩域写桩锚）为 provider 在线直接证据。
- **影响**：全 33 行 b1 锚钉零活动（anchor_before=0 / anchor_moved=false / S2 行零锚），行为面无差异；
  §5 预注册裁决与定稿结论方向不受影响（anchor 维度未被行使，对照未被污染）。若 anchor 有省 token 效应，
  则 8.1× 输入放大为低估。
- **处置（D-11）**：冻结文本不回改（保留审计链，防协议事后变形）；定稿附录同步披露
  （REPORT-20260921-hev0-p3-conclusion.md 附录 A）。anchor 维度的行使转由 P3.1 Module B（off/on 双臂）
  承担（DESIGN-20260921-hev0-p3.1-ceiling-b2.md §2，冻结 v1.0）。

## 附录 A：B0 system prompt（**冻结**，b0_prompt_sha256 记入 manifest）

```
You are an autonomous agent working in a workspace directory. You have these tools:
read_file, edit_file, execute_command, search_files, inspect_code.
Work through the user's instructions step by step, using tools as needed.
The workspace filesystem is your only persistent state: write results and
intermediate records to files when they matter later. When an instruction is
complete, answer with your final result as plain text. There is no other
memory, session, or assistant machinery: what is not in the files or the
current conversation does not exist.
```
