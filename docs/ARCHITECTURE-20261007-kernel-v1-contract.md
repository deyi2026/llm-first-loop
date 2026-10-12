# ARCHITECTURE 2026-10-07: Kernel v1 Boundary Contract

Status: **P1-4 baseline contract — current-main ratchet, not a directory rewrite**

## 1. Purpose

LFL 的“六面”是操作模型，不是源码目录结构。本契约不把仓库重构成 `kernel/` + `planes/`，而是给当前事实 runtime spine 一个可机械验证的依赖边界，阻止 capability 继续向内核反向渗透。

## 2. Physical kernel boundary

Kernel v1 的机械扫描集合：

- `src/llm_loop/core/loop/**`
- `src/llm_loop/event_log/**`
- `src/llm_loop/resources/**`
- `src/llm_loop/runtime/**`
- `src/llm_loop/llm/**`

`llm_loop.core.*` 的 session/history/message/run_context 等当前仍是 `core/loop` 的内部支撑面；本轮不做目录搬迁，因此在 import ratchet 中把顶层 `core` 视作 kernel-internal root。

`factory.py`、`config.py`、`timekeeping.py` 是 bootstrap/assembly 邻接层，P0-3 登记为 kernel-candidate，但不纳入本轮 kernel import ratchet；后续若要晋升为 kernel，必须单独做依赖审计。

## 3. Allowed direction

机械目标：

> capability / delivery / learning / evaluation 面可以依赖 kernel 公共事实与执行接口；kernel 不新增对这些面的依赖。

Kernel-internal 顶层 roots：`core / event_log / resources / runtime / llm`。

其余顶层包/模块 root 均视为非-kernel dependency root。现存反向依赖作为冻结债务登记，只允许减少，不允许增加新 edge；这里包含 capability，也包含当前尚未纳入 Kernel v1 扫描集合的 bootstrap/helper 模块（如 `config`、`timekeeping`）。

## 4. Current debt baseline

HEAD currentness AST 扫描得到以下 root-level 反向 edge（22 条）：

- `core/loop -> cache_guard`
- `core/loop -> cognitive`
- `core/loop -> config`
- `core/loop -> feedback`
- `core/loop -> introspection`
- `core/loop -> memory`
- `core/loop -> methods`
- `core/loop -> skills`
- `core/loop -> timekeeping`
- `core/loop -> tools`
- `core/loop -> workspace`
- `event_log -> memory`
- `event_log -> timekeeping`
- `llm -> cache_guard`
- `llm -> cognitive`
- `llm -> config`
- `llm -> timekeeping`
- `resources -> timekeeping`
- `runtime -> config`
- `runtime -> methods`
- `runtime -> notify`
- `runtime -> timekeeping`

这些不是“推荐依赖”，而是 P1-4 上线时的事实债务基线。任何 edge 消失时必须同步从基线删除；任何新 edge 都由 CI 拒绝。

## 5. Public-port rule

后续偿还反向依赖时优先采用：

1. kernel 定义窄 Protocol / event / immutable DTO；
2. factory/assembly 层注入 capability 实现；
3. kernel 只消费接口或事实，不 import capability concrete type；
4. 禁止为了过 guard 把 import 改成动态字符串导入或函数内隐藏导入。

本契约约束的是职责方向，不是语法游戏。

## 6. Durability relationship

Durable Run Contract 属于 kernel 级机械语义。新持久化 surface 必须在实现前声明 T1/T2/T3 或显式豁免。durability-surface registry 现通过 AST 写入原语扫描覆盖既有包内部新增文件，补上 top-level-unit guard 的盲区；registry 中 `observe` 仅代表已发现/分类，不代表合规。

## 7. Verification

`tests/unit/test_arch_guards.py`：

- AST 扫描 Kernel v1 集合的静态 import；
- 归一化到 package-level `owner -> imported_root`；
- 与 `tests/guards/function_size_baseline.json::kernel_import_edges` 精确对齐；
- 未登记新 edge → FAIL；
- 已消失 edge 未从基线清理 → FAIL；
- 基线相对 git HEAD 只允许缩小，不允许扩大。

## 8. Non-goals

- 本轮不拆 `session.py` / `history.py`；
- 不搬目录；
- 不迁移 ScheduleStore；
- 不改变生产 runtime；
- 不把六面强行映射为 Python package；
- 不声称现存 22 条反向 edge 已解决。

## 9. Exit criteria

P1-4 完成条件：

1. 本契约落盘；
2. current-main 反向 edge 基线机械可重放；
3. 合成负例证明新增 edge 会被拒绝；
4. baseline ratchet 证明不能通过“顺手登记新 edge”绕过；
5. guard focused suite 通过；
6. 无产品代码与生产服务变更。
