# REVIEW: Stage 2 Enforce Allowlist 主区应用审批

日期: 2026-09-01 | 镜像区 HEAD: c448b2f | 方案: DESIGN-20260901（rev2 五硬约束）

## 请求

批准以下两层变更应用到主区并重启三端（CLI/web/feishu）。
不批准则镜像区保持现状，主区零接触。

## 变更面

### 层 1 — Stage 2 核心（镜像区已提交 c448b2f，4 文件 +206/-3）

| 文件 | 行数 | 内容 |
|---|---|---|
| src/llm_loop/core/loop/build.py | +52 | `_cog_allowlist_hit`（L163 纯函数）+ mode 求值分支（L934: shadow 候选且名单命中→enforce；off 前置不可覆盖） |
| src/llm_loop/config.py | +5 | `cog_enforce_file`（L345 默认空）+ env `COG_RUNTIME_ENFORCE_FILE`（L660，不做存在性校验——读取方每轮 fail-closed） |
| src/llm_loop/cognitive/telemetry.py | +4 | 三字段归因: mode(effective)/configured_mode/promoted（packet_compile/tier_degraded/state_rebuild 同套） |
| tests/unit/test_cr_r1_mode.py | +148→227 行 | 18 用例 |

### 层 2 — 测试债修复（工作区未提交，2 文件 +7/-1，与本特性无功能耦合）

| 文件 | 变更 | 原因 |
|---|---|---|
| src/llm_loop/introspection/task_store.py | +2 | L360 裸 `except ValueError: pass` 补 fail-open 注释（违反"fail-open≠fail-silent"卫生规则，Task Frontier 线遗留） |
| tests/unit/test_introspection.py | +5/-1 | 工具清单断言 `==` 改 `>=`（注册表随 EVO 演进动态扩 8 工具，静态全量断言与演进机制冲突；基线集合仍防工具丢失） |

注: git 工作区另有 web 线 11 文件改动，**不在本次审批范围**，主区应用不触碰。

## 五硬约束 → 实现 → 测试映射

| 约束 | 实现 | 测试 |
|---|---|---|
| P0-1 控制面分离 | 仅绝对路径生效；相对路径=无效 | test_s2_relative_path_invalid |
| P0-2 fail-closed 全语义 | 缺失/OSError/超限→shadow；off 硬关前置 | test_s2_missing_file / oserror_fail_closed / off_hard_blocks_allowlist |
| P1-3 硬上限 | 64KiB + 256 条目 | test_s2_oversize_64kib / over_256_entries |
| P1-4 telemetry 三字段 | mode+configured_mode+promoted | test_s2_promoted_telemetry_fields + 冒烟 S1b（真实落盘） |
| P1-5 热更/prospective rollback | 每轮重读，删行下一轮回 shadow | test_s2_hot_removal_round_n_n1 + 冒烟 S3 |

## 验证证据

- 18 focused 单测全绿（test_cr_r1_mode.py, 18 dots [100%] exit 0）
- 全量回归 tests/unit PYTEST_EXIT=0（修复层 2 后复跑；修复前 2 FAILED 均为 Task Frontier 线遗留，非本特性回归）
- 冒烟 6/6（真实文件系统+真实 Settings+telemetry 真落盘）: data_ab/stage2-allowlist-smoke-20260901.txt
  - S1 命中→enforce / S1b 三字段落盘 / S2 未命中→shadow / S3 热删回退 / S4 off 硬关+求值解耦 / S5 相对路径无效

## 主区应用步骤（批准后执行）

1. 复制 6 文件: 层 1 四文件（取镜像区 c448b2f 版本）+ 层 2 两文件
2. 主区跑 test_cr_r1_mode + test_silent_pass_cleanup + test_introspection + 全量 tests/unit
3. 主区当前 .env 无 COG_RUNTIME_ENFORCE_FILE → 默认行为不变（全 shadow），零行为差异
4. 重启 CLI/web/feishu 三端（需用户确认时机）
5. Stage 2 实跑（DESIGN §6）: 1 个真 session 写入名单提升 enforce，观察 telemetry promoted=true + 与 shadow 会话比对
