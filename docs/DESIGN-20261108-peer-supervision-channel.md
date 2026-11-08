# DESIGN-20261108 Peer 有人在场（supervised）执行通道

- 状态：设计稿，**未实施**。本文只定义契约与判定链，不代表任何代码已生效。
- 上游设计：`docs/DESIGN-20261107-deepin-remote-takeover-agent-interop.md` §5.2 / §5.7.3（D10 / D13 / D15）
- 对应任务：T9-b（`TASK-3f142c52-009` 第二段）
- 前置切片：T9-a 已落地（`feat/peer-fs-write-gate-20261108` @`65e44778f`，执行器 + 闸4）

## 0. 已核实现状（2026-11-08 读码，非推测）

| 事实 | 位置 |
|---|---|
| `fs.write` 执行器与闸4 已实现；参数 `path` / `content_b64` \| `artifact_ref` / `overwrite` / `create_parents` | `src/llm_loop/peer/executor.py::_run_fs_write` |
| `EXECUTABLE_KINDS` 仍只有 `fs.read` / `fs.list`，manifest 不播报 `fs.write` | `src/llm_loop/peer/kinds.py:53` |
| 准入编排把 `supervised=False` 写死，`fs.write` 一律 `requires_supervised_execution` | `src/llm_loop/peer/service.py:200` |
| `policy.require_supervision` 已支持 `supervised=True` 放行 | `src/llm_loop/peer/policy.py:72` |
| 状态机 10 个状态，无 `awaiting_supervision` | `src/llm_loop/peer/state.py:13` |
| `receipt.schema.json` 的 state enum 与上面 10 个一致 | `docs/schemas/lfl.peer.v1/receipt.schema.json` |
| `task-submit.schema.json` `additionalProperties: false`，无 `supervised` 字段 | 同上目录 |
| 契约 P1 的 `example-kinds==registry` 零漂移检查**尚未落地** | `scripts/verify_peer_schemas.py` 无该检查 |
| 写域根未注入即全拒；策略层不读进程环境，读取点收敛在 `config.load_settings` | `src/llm_loop/peer/write_gate.py` / `src/llm_loop/config.py` |

## 1. 问题：三个必须同时成立的条件

P1 的授权模型是**无人值守**：控制端派单，受控端自动执行。`fs.write` 是 `non_idempotent`，按契约必须 `supervised_only=True`。要让它在不破坏无人值守模型的前提下可用，需要同时满足：

1. **可发现**：控制端能从 manifest 知道"这台节点能写"。
2. **不可自授**：控制端不能自己把 `supervised` 变成 `true`——否则闸3 的 `requires_supervised_execution` 形同一句注释。
3. **逐次在场**：受控端的操作者必须看到**将要发生的具体副作用**（写哪个路径、多少字节、什么摘要），并对**这一次**同意。任何"记住这个 kind 以后都同意"都退化成无人值守。

条件 2 有一层已有保障：`task-submit.schema.json` 是 `additionalProperties: false`，控制端塞 `supervised: true` 会被 schema 直接拒。本文不依赖这一条作为唯一防线，但它是第一道。

## 2. 决策

### D1 默认关闭，显式开启

`LFL_PEER_SUPERVISION` 缺省为 `0`。缺省时行为与今天完全一致：`fs.write` 不宣告、派单得 `requires_supervised_execution`。

原因：开一条"远程请求 + 本机人点确认"的通道，是把人的注意力变成可被远程消耗的资源。它必须是操作者的显式选择，不能因为升级 wheel 就自动打开。

### D2 新增状态 `awaiting_supervision`

不是 `denied`，也不是 `blocked`：

- `denied` 是终局，控制端会认为能力不存在，无法再确认；
- `blocked` 在现有恢复逻辑里属于"执行中阻塞"，重启走 `unknown_outcome`，语义不符；
- `awaiting_supervision` 是**副作用之前**的等待态，重启后应保留等待，而不是判成结果不明。

迁移（只增边，不改既有边）：

```
submitted            -> awaiting_supervision | admitted | denied | cancelled | failed
awaiting_supervision -> admitted | denied | cancelled | failed
```

`TERMINAL_STATES` 不变（`awaiting_supervision` 非终局）。`recover_stale` 的扫描集合 `("admitted","queued","running")` 不包含它——重启不会误判；过期由 D6 单独处理。

### D3 确认 = 本机 TTY CLI，逐次、一次性、绑定参数摘要

新增 `src/llm_loop/peer/operator.py`，入口 `python -m llm_loop.peer.operator`：

- `list`：列出 `awaiting_supervision` 的任务，显示 `task_id` / `kind` / `path` / `bytes` / `sha256` / 过期时间。
- `confirm <task_id>`：展示完整参数摘要 → 要求操作者键入 `task_id` 后 6 位 → 写确认票据 → 执行。
- `reject <task_id>`：任务转 `denied / supervision_rejected`。

硬约束：

- **TTY 校验**：`sys.stdin.isatty()` 为假直接拒绝。管道、脚本、自动化不能代替人确认。
- **票据绑定**：票据记录 `task_id + params_digest + expires_at + confirm_nonce`。执行前重算 `params_digest` 并与票据比对，不一致 → `supervision_mismatch`。
- **一次性**：确认写入用 CAS 把 `consumed_at` 从空置为时间戳；重放同一票据 → 拒绝。
- **TTL**：票据有效期 `min(task.deadline_s, LFL_PEER_SUPERVISION_TTL_S)`，缺省 300 秒。到期未确认 → `denied / supervision_timeout`。
- **同一份配置**：CLI 必须与受控端服务使用同一个配置来源（`config.load_settings()`，或同一个显式 `--write-root`），不能各读各的环境。CLI 启动时打印实际生效的 `data_root` / `write_root` / `node_id`，并校验 data 目录属主等于当前 uid，不一致即拒绝。`write_root` 缺失时闸4 全拒——fail-closed，不会因为环境错配而越权写。策略层（`write_gate`）不读进程环境，只接受注入值。

### D4 确认即执行（同进程），不做后台轮询

`confirm` 在写完票据后，**在同一进程内**构造 `PeerService` 并执行该任务，然后把回执打印给操作者。

理由：

- 后台 watcher 需要常驻进程、开机自启、自身崩溃恢复，P1 没有这份预算；
- 人确认的瞬间就是执行的瞬间，中间窗口最短，不需要解释"为什么我同意了但十分钟后才写"；
- 代价是 CLI 崩溃会把任务停在 `running`——由现有 `recover_stale` 走 `unknown_outcome`（D13 已有语义），不自动重试。这个代价是已知且可接受的。

### D5 宣告面条件化：handler 存在 ≠ 可以宣告

`EXECUTABLE_KINDS` 回答的是"有没有 handler"；宣告还要回答"这台机器的配置是否完备"。两者分开：

```
advertised = EXECUTABLE_KINDS | ({"fs.write"} if supervision_enabled and write_root_set else ∅)
```

`manifest_kinds()` 增加一个显式的 `executable` 参数，缺省仍取 `EXECUTABLE_KINDS`（向后兼容）；受控端构造 manifest 时传入按本节点配置算出的集合。

结果矩阵：

| supervision | write_root | manifest 播报 fs.write | 派单结果 |
|---|---|---|---|
| 0 | 任意 | 否 | `requires_supervised_execution` |
| 1 | 未配 | 否 | `requires_supervised_execution`（不播报即不该被派） |
| 1 | 已配 | 是 | `awaiting_supervision` → 确认后执行 / 超时 deny |

不新增 manifest 字段：kind 级 `supervised_only: true` 已经表达"这个 kind 需要人确认"，控制端从现有 schema 就能读到。`manifest.schema.json` 是 `additionalProperties: false`，加 node 级字段要动契约，收益不抵成本。

### D6 闸3 在执行前重判，不只信确认时的结论

从"确认"到"执行"之间，租约可能过期、被撤销、额度被别的任务用掉。因此 `resume_supervised` 的顺序固定为：

```
载入票据 → 验未消费 / 未过期 → 重算 params_digest 比对
  → evaluate(supervised=True)   # 租约/kind/路径全部重判
  → 执行器（内部再走闸4）
```

任何一步失败都落 `denied` 并带具体 `reason_code`，不执行。

### D7 四道闸对 supervised 任务全量生效

supervision 只改变"谁允许放行"，不改变"放行后能做什么"：

- 闸2 租约：同样校验 `allowed_kinds` / `allowed_paths` / 额度 / 并发；
- 闸3 策略：同样校验参数形状与路径包含；
- 闸4 写域：`config.PeerSettings.peer_write_root`（注入值）/ symlink / 封条 / 敏感路径，一条不少；
- 审计：确认事件与执行事件都落 `data/peer/`。

这一条必须有测试钉住（见 §4 的 T8），否则"有人在场"会变成"可以网开一面"的暗门。

## 3. 数据与审计

确认票据：`data/peer/supervision/<task_id>.json`

```json
{
  "schema": "lfl.peer.supervision.v1",
  "ticket_id": "sup_...",
  "task_id": "task_...",
  "node_id": "node_...",
  "kind": "fs.write",
  "params_digest": "sha256:...",
  "issued_at": "...",
  "expires_at": "...",
  "consumed_at": null,
  "confirmed_by_uid": null
}
```

写入沿用现有磁盘权威 + CAS 模式（对齐 `admission.py` / fleet 的写法），不复用任务存储文件。

审计事件（`data/peer/`）：`supervision_requested`、`supervision_confirmed`、`supervision_rejected`、`supervision_expired`、`supervision_mismatch`。每条带 `task_id` 与 `admission_id`，保证"每次写都能追到是谁在哪台机器上同意的"。

新增 `reason_code`（须同步 `reason-codes.json` 与 receipt schema 的 enum 一致性检查）：

- `supervision_timeout`
- `supervision_mismatch`
- `supervision_not_configured`
- `supervision_rejected`

## 4. 验收与测试

单测（不需要真机）：

| 编号 | 场景 | 期望 |
|---|---|---|
| T1 | supervision 未开启，派 `fs.write` | `denied / requires_supervised_execution`（现状回归） |
| T2 | 已开启但无票据直接调执行器 | 拒绝；执行器不自判 supervised |
| T3 | 票据过期后确认 | `denied / supervision_timeout` |
| T4 | 票据 `params_digest` 与任务不符 | `denied / supervision_mismatch`，不执行 |
| T5 | 同一票据确认两次 | 第二次拒绝（`consumed_at` 非空） |
| T6 | 正常确认 → 写成功 | 回执 `succeeded`，`file_effect` 含 `path`/`bytes`/`sha256`，不含内容 |
| T7 | 确认后、执行前租约被撤销 | `denied / grant_revoked` |
| T8 | 确认后目标路径越出 `LFL_PEER_WRITE_ROOT` | `denied / sandbox_denied`（supervision 不放宽闸4） |
| T9 | 非 TTY 调 `confirm` | 拒绝，票据不写入 |
| T10 | 宣告矩阵三行 | 与 §2 D5 表格逐行一致 |

回执层重测：

- **U5（部分副作用后 kill -9）**：在 `running` 期间杀进程，重启后应为 `unknown_outcome`，不自动重试。T9-a 未覆盖副作用前提，T9-b 补测。
- **U7（`desktop.type` 注入）与 `fs.write` 无关**，不在本任务范围。`docs/peer-implementation-brief.md` 旧表述把 U5/U7 并列写在 T9-b 下，此处更正：U7 属 P2-B 桌面面。

## 5. 与契约 P1 修复的衔接

- T9-b 要改 `docs/schemas/lfl.peer.v1/examples/manifest.example.json`（播报 `fs.write`）与 `receipt.schema.json`（state enum）。
- 契约 P1 修复会加 `example-kinds == registry` 零漂移检查；同改一个 example 文件会冲突。
- 顺序：**契约修复先合，T9-b 后合**。若届时检查仍未落地，T9-b 的提交必须手工核对 example 与运行时 registry 一致，并在提交信息里写明"该检查未落地，手工核"——不得声称已被自动检查覆盖。

## 6. 明确不做

- 不做远程确认：控制端无法替受控端确认，也没有"确认"接口。
- 不做批量/记忆式同意：那等于关掉 supervision。
- 不做 GUI 确认弹窗：P1 没有受控端桌面 UI 面（P2-B 才讨论）。
- 不放宽闸4 / bwrap / 审计：supervision 只改放行主体，不改边界。
- 不允许 `fs.write` 写 LFL 自身代码与数据目录：由封条与敏感路径规则覆盖，T8 之外再加一条显式测试。

## 7. 未决

1. `operator.py` 的入口形态：`python -m llm_loop.peer.operator` 还是 `scripts/peer_operator.py`。倾向前者（与包同版本发布，不额外维护脚本）。
2. 票据 TTL 缺省 300s 是否合适（等待人走到机器前的时间）。可按实测定，但必须有上限。
3. 服务端是否需要"有任务在等确认"的被动提示（manifest `health` 加 `supervision_pending` 计数）。这会动契约，倾向 P1 不做。
