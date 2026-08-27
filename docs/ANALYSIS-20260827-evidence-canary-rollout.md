# Evidence 生产启用 Canary 方案（批次2 设计稿）

> 关联: EVO-20260827-ed4c1350 批次2 | GOAL-20260827-27d22a8e | 审计报告 P0-1
> 状态: 设计稿待审批 | 2026-08-27

## 一、前提核验（2026-08-27 本轮完成）

| 前提 | 结论 | 证据 |
|---|---|---|
| R0 阻塞①pipeline ordering 集成 | **已解除** | R12 契约已实现: registry `_lock_pipeline_for_evidence_enforce` 装配期 fail-closed（有 hook 拒绝装配）; test_evidence_pipeline_integration 5/5 passed |
| R7-V2 可恢复性 | PASS | 24/24, exact 95.83%, stale-as-current=0, REMEDIATION CLOSED |
| mode 枚举 | off/shadow/enforce | config._env_evidence_mode; canary=运营策略非新 mode |
| .env 现状 | EVIDENCE_MODE 未设(=off), TOOL_PIPELINE_ENABLED=1 | R0 时 pipeline 开启曾阻塞 enforce, R12 后兼容（无 hook 前提下） |

## 二、三段 Canary 路线

### C0 — 主区 shadow（申请批准后直开）
- 动作: 主区 .env `EVIDENCE_MODE=shadow` + 重启
- 性质: dual-write（ledger/blob 落盘）不改模型可见 prompt/工具结果——R0 已证架构 eligible
- 观察窗: 24h 或 ≥10 真实会话
- 通过标准: ①写入零异常（error 日志为零）②会话行为零差异（抽查 3 会话 diff 模型可见面）③GC/引用计数无泄漏（blob 目录体积合理）
- 风险: ≈0; 回退: 删一行重启

### C1 — 镜像区 enforce（受控 canary）
- 动作: 镜像 .env `EVIDENCE_MODE=enforce`（镜像 8903 本身即协议验证环境=天然 canary）
- 任务集: 3-5 个真实多轮任务（必含: ①触发压缩的长会话 ②重读源场景——同文件两轮读取 ③跨会话恢复场景）
- 观察指标（审计报告 P0-1 清单）:
  | 指标 | 采集方式 | 通过线 |
  |---|---|---|
  | source reread without change | 会话 JSON 复算（同 path 同版本重复 read_file） | 较 off 基线下降或不升 |
  | exact duplicate tool call | 会话 JSON 复算 | =0 |
  | evidence hydration rate | 模型实际调用 read/search_evidence 次数 / 恢复需求次数 | >0（能力被使用） |
  | manifest 注入 | build 时注入条数 | ≤8（bounded） |
  | cache hit | guarded_requests/cache_health 复算 | 不劣化 >10pp |
  | 任务成功率 | 人工判定 | 无回归 |
- 硬回退条件（任一触发即退回 shadow）: hydration=0 且 reread 上升 / cache 跌 >10pp / 任务失败归因 evidence
- 遥测方式: **事后复算**（会话 JSON + event log），不预建仪表——避免为观测改生产代码; 若复算成本高再提演进建 evidence_ops.jsonl

### C2 — 主区 enforce + 默认化
- 动作: 主区 .env enforce → 48h 观察窗（同 C1 指标）→ 达标后提演进建议改 config 默认值（单独审批）
- provider 对照: C1/C2 各覆盖 deepseek+glm ≥1 任务

## 三、决策请求
1. **C0 批准**（主区 shadow, 一行 .env, 零模型可见影响）
2. C1 镜像 enforce 由 AI 在镜像执行+实测（协议内自主）
3. C2 与默认值变更: 届时凭 C1 数据再批
