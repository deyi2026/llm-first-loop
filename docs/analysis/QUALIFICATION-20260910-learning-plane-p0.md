# QUALIFICATION-20260910：Learning Plane P0

> 状态：**QUALIFIED on feature candidate**
> 总 Architecture SoT：`docs/DESIGN-20260910-adaptive-reasoning-learning-architecture.zh.md`
> 专项设计：`docs/DESIGN-20260910-learning-plane.md`
> 原始 live qualification 分支：`feature/learning-plane-p0a-20260910`；clean publication 分支：`feature/adaptive-learning-p0-clean-20260910`。后者从 `lfl/main@d59169f` 按 Architecture / implementation / qualification 三层重建，不包含原混合提交中的 R9/CI guard 变更；两者均未据本报告执行 production rollout。

## 1. 验证范围

本次只裁决最新版总设计 Phase 1 / Learning Plane P0：

1. Task 完成关键路径不再同步等待 Reflection LLM；
2. Reflection 材料绑定真实 durable Episode；
3. model-facing Method candidate 的 source Episode provenance 由 runtime 推导；
4. qualification Episode identity 由 runtime 推导，模型不能用自报 ref 制造“独立验证”；
5. Learning 是独立 ReflectionRun，不占用户 Session lease；
6. foreground run 在 Learning admission 前拥有机械优先级；
7. foreground 探测覆盖同进程 background/sync run 与跨进程、跨 workspace 的 run lease；
8. LearningJournal 具备 durable lifecycle / idempotency / crash reconcile；
9. alternate Web + 当前真实本地模型完成 live qualification。

本阶段**不**宣称已完成统一 Resource Governor、云端 RPM/TPM/成本治理、真正请求级抢占、Reasoning Lab 或 Meta-Learning；这些属于后续 Architecture SoT 阶段。

## 2. 审查中发现并关闭的 P0 缺口

### 2.1 Production `current_episode_ref()` 断点

原状态：`RegistryHost` 声明了 `current_episode_ref()`，但 production `CorrectionToolRegistry` 没有实现；测试 FakeHost 自行实现该方法，遮住了 production 缺口。model-facing `save_candidate` 因异常 fail-open 可能保存 `source_episode_refs=[]`。

修复：

- `CorrectionContext` 增加独立 mechanical `current_episode_ref_resolver`；
- Engine 在活跃 run 上用当前 bound session、`_run_sessions[sid]`、per-session `current_turn_ref` 和 `stable_episode_ref()` 推导 current Episode；
- 只有 genuine human user turn 可生成 provenance；
- 不使用 `latest_episode()` 代替 current turn，避免同 Session 上一任务串入；
- model-facing candidate 缺失 runtime Episode provenance 时拒绝写入，而不是静默保存空 provenance。

最终 Episode indexing 与该 resolver 使用同一个 `stable_episode_ref(session_id, user_message, user_seq)`，因此运行中得到的 ref 与最终 durable Episode ref 同源确定。

### 2.2 Qualification identity 可由模型伪造

原状态：model-facing `method_manage(record_qualification)` 接受自由字符串 `task_ref`；Store 只校验 `episode:` 前缀与“不同于 source ref”，因此模型可构造看似独立但不存在的 Episode ref。

修复：

- model-facing schema 移除 `task_ref`；
- handler 忽略任何 legacy/额外 caller `task_ref`；
- qualification identity 强制读取 runtime current Episode；
- 持久 receipt 新增 canonical `qualification_episode_ref`；
- `task_ref` 仅作为旧 reader 的兼容 alias，二者当前写入同一 runtime-derived ref；
- source Episode 与 qualification Episode 相同的 `promotion=pass` 继续机械拒绝。

语义 verdict / mechanism / task benefit / promotion 仍由模型判断；程序只证明 Episode 身份和来源。

### 2.3 Foreground gate 错把 ToolRegistry 当运行中任务

原状态：`LearningPlane.foreground_busy()` 检查 `bool(engine.registry)`；这里的 `engine.registry` 是 ToolRegistry，正常情况下恒 truthy，可能导致 Learning 永久 queued。

修复后只读取机械运行事实：

```text
BackgroundRunner.has_running()
OR guarded engine._sync_active
OR held *.run.lock
```

读取不确定时 fail-closed：Learning 让路，不阻断 foreground。

### 2.4 跨进程 workspace run lease 漏检

原状态：只扫描 `sessions/*.run.lock`；真实 SessionStore lease 位于：

```text
sessions/<workspace>/<session>.run.lock
```

因此会漏掉 workspace partition 下的前台进程。

修复：从 sessions 根递归扫描 `**/*.run.lock`。Learning 保护的是共享 provider/runtime，所以任一 workspace 的真实 foreground lease 都应获得优先级。

## 3. 自动化回归证据

新增/强化的关键行为测试包括：

- production Registry 从 active genuine human turn 推导与 `stable_episode_ref()` 相同的 Episode ref；
- model-facing candidate 在 runtime provenance 缺失时拒绝；
- spoofed caller `task_ref` 不能改变 qualification provenance；
- ToolRegistry truthiness 不再等价于 foreground busy；
- BackgroundRunner active / sync active 会使 Learning yield；
- admission 后、start 前出现 foreground 时 Learning requeue，且不会消耗 attempt / 调用模型；
- nested workspace held `*.run.lock` 可被跨进程 probe 检出；
- 故意阻塞 ReflectionRun 时，Web SSE `done` 仍先返回；
- Reflection 阻塞期间，同一用户 Session 的下一 genuine user turn 仍可完成。

验证结果：

```text
focused provenance gate: PASS
Learning/SSE critical-path gate: PASS
adjacent Learning/Runner/Config/Web gate: PASS
full pytest tests -m 'not real_llm': PASS / exit 0
Ruff src+tests: PASS
Pyright repository: 0 errors / 0 warnings
git diff --check vs lfl/main: PASS
git security scan tracked tree: PASS
Goal changed/untracked file privacy scan: PASS
```

`ruff check .` 不作为仓库资格判定：仓库根含明确隔离且不属于本工作线的 `.tmp/pytest-*` 合成树与 `.worktrees/*`，其中存在测试生成的 lint 反例；正式源码口径 `src + tests` 全绿，隔离目录未被本阶段修改或清理。

## 4. Alternate Web live qualification

### 4.1 隔离条件

- alternate Web 使用 loopback 临时端口与独立 `DATA_DIR` / `LFL_DATA_DIR` / `METHODS_DIR`；
- `LEARNING_PLANE_ENABLED=1`；
- `METHOD_REFLECTION_MODE=auto`；
- friction threshold 在 canary 中机械调低到 1 round，以保证产生 Learning job；
- 复用已经运行的 `cognilocal/ornith-1.5-35b-a3b-mlx`；
- 没有加载第二个本地大模型；
- production Web 与现有本地模型服务均未重启、未替换。

### 4.2 Task -> Episode -> enqueue -> done

第一轮真实请求确认：

- request route 与 `done.model_used` 均为 `cognilocal/ornith-1.5-35b-a3b-mlx`；
- final answer 正常完成；
- durable `run.end` 后立即产生 `learning.enqueued`；
- `learning.enqueued.source_episode_ref` 与 EpisodeStore record 及 Session assistant metadata 的 `resolved_episode_ref` 完全一致；
- SSE `done` 不等待 Reflection 完成。

一组真实时序：

```text
00:44:33.506730Z  first foreground run.end
00:44:33.507713Z  first learning.enqueued
```

### 4.3 Foreground priority

第一轮 done 后立即在**同一 Session**发起第二个较长 foreground 请求，使其跨越第一条 Learning 的 15 秒 quiet boundary。

在第一条 job 入队后第 17 秒：

```text
second foreground: still running
first Learning events: [queued]
```

明确不存在 `admitted` / `started`。

第二个 foreground 随后正常完成：

```text
00:45:17.831664Z  second foreground run.end
00:45:17.832510Z  second learning.enqueued
00:45:20.349172Z  first Learning admitted
00:45:20.350074Z  first Learning started
00:45:27.754832Z  first Learning none
```

因此第一条 Learning **只有在第二个 foreground 完成后**才获得 admission；不是仅靠单元测试推断。

本次 ReflectionRun 真实调用当前 Ornith，约 7.4 秒完成，合法返回 `none`：该 source Episode 是固定字符串指令跟随任务，没有可复用的绕路方法。`none` 被 durable journal 记录，而不是被重复反思。

## 5. 当前能力边界

P0 的 foreground-first 保证是：

> 在后台模型请求尚未真正进入 provider 之前，只要 runtime 能观察到 foreground 活跃，Learning 不获得 admission；Task 完成关键路径永不等待 post-task Learning。

P0 **不**宣称对已经发出的单并发本地 LLM 请求可以强制抢占。若 Learning 已经进入一个不支持 cancellation/priority 的 provider，而新 foreground 随后到达，严格 preemption 需要后续统一 Resource Governor 与 provider cancellation/priority contract。

同理，P0 还没有统一处理云端 provider 的：

- concurrency reserve；
- RPM / TPM；
- quota / 429；
- background cost accounting；
- trust-domain aware learning-provider routing。

这些属于总 Architecture SoT 的下一阶段，不能把当前 local admission gate 误称为完整 Resource Governor。

## 6. P0 裁决

**Learning Plane P0 对本 feature candidate 达到 QUALIFIED。**

当前已证明：

```text
Task completion
  -> durable Episode
  -> durable Learning enqueue
  -> SSE done / Session lease release
  ================================
  -> foreground-aware admission
  -> independent ReflectionRun
  -> durable terminal learning state
```

且 source / qualification provenance 已从“模型可声明字符串”收回为 runtime mechanical identity，不改变模型对 Method 内容、适用性、验证结果和 promotion 意义的判断权。

下一阶段应按总 Architecture SoT 进入 **provider-agnostic Unified Resource Governor**，先统一本地与 GLM / MiniMax / DeepSeek 等云端资源事实，再在其上实现 Reasoning Lab；不能继续把资源调度逻辑堆进 Method Learning 私有模块。
