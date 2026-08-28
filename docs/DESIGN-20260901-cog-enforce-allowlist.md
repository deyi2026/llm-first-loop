# DESIGN-20260901: Cognitive Runtime Enforce Allowlist（Stage 2）

状态: 待用户审批 | 前置: Enforce Canary Stage 1 PASS（f9ac092，五门全过）
路径: 用户升级判定 —— 真实隔离会话 allowlist → 少量生产任务 enforce → default 仍 shadow

## 1. 目标与边界

- **default 不动**: `COG_RUNTIME_MODE` 全局默认 shadow，本设计零改变
- **session 级提升**: 仅名单内 session 在运行时提升为 enforce（真实隔离会话逐个尝试）
- **快速 rollback**: 删名单文件或删行，下一轮 build 即生效（无需重启进程）
- **不做**: 全局 enforce、session-prefix 通配、COLD 接入（按用户指示 COLD 为后续独立设计项）

## 2. 机制

```
优先级（build cognitive 段，每轮求值）:
  mode=off        → 永不 enforce（硬关，名单无效）
  mode=shadow     → sid ∈ allowlist ? enforce(promoted) : shadow
  mode=enforce    → 全局 enforce（名单冗余，promoted 不标注）
```

- 名单文件: `COG_RUNTIME_ENFORCE_FILE` env（默认空=禁用；指向如
  `data/audit/cog_enforce_allowlist`，每行一个 session_id，`#` 注释）
- **每轮 build 重读**（文件预期 ≤10 行，IO 开销可忽略；热更语义由此成立）
- 读失败/文件缺失 → 名单空（fail-open 到 shadow，不阻断会话）

## 3. 变更面（镜像工作区实施，主区零接触直至批准应用）

| 文件 | 变更 | 规模 |
|---|---|---|
| config.py | `cog_enforce_file: str = ""` + env 解析（路径字符串，不校验存在） | ~8 行 |
| build.py | L896 mode 求值后 + 名单提升分支（读文件→sid 匹配→_cog_mode="enforce"） | ~12 行 |
| telemetry.py | packet_compile 事件 + `promoted: bool` 字段（allowlist 来源） | ~4 行 |
| tests/unit/test_cr_r1_mode.py | 4 用例: 命中提升/未命中保持 shadow/off 硬关/文件热更生效 | ~60 行 |

## 4. 验证计划

1. 单测 4 用例 + 既有 173 focused 全绿（零回归）
2. 端到端: canary driver `phase=enforce` 复跑 1 run 经名单机制（driver 改写名单文件
   而非 env mode）——验证 promoted 标注 + 全轮 warm 与 env 路径同构
3. Stage 2 实跑（本设计批准后另行执行）: 1-2 个真实隔离会话（CLI 发起）进名单 →
   观察五门指标 → 移除名单 → 会话自然回 shadow

## 5. 风险与对策

- 名单文件误写全局 sid → 仅该 session 提升，default 仍 shadow（爆炸半径=1 会话）
- 热更竞态（写入中途 build 读）→ 读到部分行=漏提升，下轮自愈（fail-open 安全侧）
- promoted 会话观察期异常 → 删行 rollback，会话下一轮回 shadow；已注入 packet 的
  历史轮不受影响（envelope 分片独立，批次 A 已锁）
