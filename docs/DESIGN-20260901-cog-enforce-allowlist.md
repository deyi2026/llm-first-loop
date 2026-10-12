# DESIGN-20260901: Cognitive Runtime Enforce Allowlist（Stage 2, rev2）

状态: APPROVED WITH CONDITIONS（用户 2026-09-01 批准，5 硬约束已并入）
前置: Enforce Canary Stage 1 PASS（f9ac092）
路径: 真实隔离会话 allowlist → 少量生产任务 enforce → default 仍 shadow

## 0. 审批硬约束（本版全部并入，实施逐条对应）

| # | 约束 | 实施 |
|---|---|---|
| P0-1 | 名单=control-plane authorization state，operator-owned；不得位于 agent 可写目录（data/audit、workspace）——防 self-promotion | 路径语义: 绝对路径 + **运行用户不可写（os.access W_OK 拒绝）双条件**（review R3：绝对路径是必要非充分条件——同 Unix 用户下 ~/.config 类路径可写，self-promote 攻击链闭合）。推荐 `/etc/lfl/cog_enforce_allowlist`（root/operator 所有，LFL 运行用户只读）；`~/.config/lfl/` 在同用户执行模型下**不构成安全边界**。root 运行时 os.access 恒真，须配合只读挂载/容器。**相对路径=配置无效→fail-closed shadow**。COG_RUNTIME_ENFORCE_FILE 已从 execute_command 子进程环境剔除（控制面 capability metadata，agent 无业务理由可见） |
| P0-2 | promotion fail-closed: 文件缺失/读取失败/格式异常/超限 → shadow；mode=off 永远硬关，名单不可覆盖 | `_allowlist_hit` 全异常捕获返回 False；off 分支在名单判断之前 |
| P1-3 | 每轮读取硬上限: ≤64 KiB、≤256 有效条目（防无界读取） | stat().st_size > 65536 → False；有效行 > 256 → False |
| P1-4 | telemetry: `mode`=effective_mode，另加 `configured_mode` + `promoted`；packet_compile / tier_degraded / state_rebuild 同套归因 | emit 事件统一三字段 |
| P1-5 | rollback=prospective: 删行下一轮恢复 shadow；已注入 enforce 历史不撤销；严重异常→删名单+从最后 verified checkpoint 开新 session | §5 语义改写 |

## 1. 目标与边界（不变）

- default 不动: COG_RUNTIME_MODE 全局默认 shadow
- session 级提升: 仅名单内 session 运行时提升 enforce
- 不做: 全局 enforce、prefix wildcard、COLD 接入

## 2. 机制（每轮 build 求值）

```
configured off        → off（硬关，名单无效）
configured shadow
  + sid miss          → shadow
  + sid hit           → enforce, promoted=true
configured enforce    → enforce, promoted=false

allowlist 解析（fail-closed 全语义）:
  COG_RUNTIME_ENFORCE_FILE 为空            → 名单禁用（shadow）
  相对路径                                  → 配置无效（shadow）
  文件缺失 / OSError / 编码异常             → shadow
  st_size > 64 KiB                         → shadow
  有效条目（非空非 # 注释行）> 256           → shadow
```

## 3. 变更面（镜像工作区）

| 文件 | 变更 | 规模 |
|---|---|---|
| config.py | `cog_enforce_file: str = ""` + env 直读（不做存在性校验——fail-closed 归读取方） | ~6 行 |
| build.py | `_cog_allowlist_hit()` 纯函数（P0-2/P1-3 全约束）+ mode 求值分支（off 前置） | ~30 行 |
| telemetry.py | 事件 schema: mode(effective)/configured_mode/promoted 三字段 | ~8 行 |
| test_cr_r1_mode.py | 原 4 用例 + 新 7 用例 | ~140 行 |

## 4. 验证计划

1. 单测 11 用例:
   - 原 4: 命中提升/未命中 shadow/off 硬关/热更生效
   - 新: missing/unreadable/oversize/超条目/相对路径 → shadow（5 用例）
   - 新: promoted telemetry（configured_mode=shadow, mode=enforce, promoted=true）
   - 新: configured enforce 时 promoted=false（名单不叠加）
2. E2E 热删机械锁定: round N promoted=true/enforce → 删 sid → round N+1 promoted=false/shadow
3. 端到端: canary driver 1 run 经名单机制（名单文件置于 /tmp，operator 脚本写入，非 agent 路径）
4. 既有 173 focused 全绿零回归

## 5. Rollback（prospective，改写）

删名单/删行 → **下一轮** build 起恢复 shadow；**此前已注入 prompt 的 enforce 轮历史不撤销**。
严重异常（如 promote 后行为劣化）处置: ①删名单止增量 ②从最后 verified checkpoint 开新
session 承接（不假设原会话完全回滚）。名单文件本体建议 operator 保留审计副本。

## 6. Stage 2 实跑（批准后另行执行）

1-2 个真实隔离 session → operator 写名单（绝对路径）→ 少量真实任务 → 观察五门 →
删名单回 shadow。不扩大 global enforce，不接 COLD。
