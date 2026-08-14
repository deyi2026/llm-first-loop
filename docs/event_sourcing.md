# 事件溯源（Event Sourcing）

> B8(2026-08-14) 公开化文档：单一真相源设计 + 使用/迁移指南。
> 实现：`src/llm_loop/event_log/`（model/store/replay/reconcile/inventory/migrate/
> rotate/retire/hooks/fork）；开关 `EVENT_LOG_ENABLED`（默认 1）。

## 一、为什么事件溯源

会话/记忆/审计等**派生视图**（session JSON、action_trace、压缩档案）在多进程并发写、
截断、降级路径下可能互相不一致。事件日志（append-only JSONL）作为**轨迹单一真相源**：

- 每个事实只写一次（追加），派生视图可随时从事件**重放重建**（幂等）
- 双轨并存期可**逐字段对账**（reconcile），不一致如实标注
- 迁移/退役可**逐字节回滚**（备份区），不丢数据

## 二、事件类型（5 类）

| 事件 | 触发点 | payload 要点 |
|:---|:---|:---|
| `session.created` | 会话首次落库 | 顶层字段快照（title/status/model_override/...） |
| `message.appended` | 每条消息落库 | role/content/source/tool_call_id/status/tool_calls/reasoning |
| `context.compressed` | 历史压缩 | 压缩元信息（可配合 search_archive 找回原文） |
| `session.meta_changed` | 重命名/置顶/通道/归档 | 变更字段 |
| `session.forked` | 会话 fork | fork 点/元信息 |

事件必填字段：`session_id`（回放定位）+ `seq`（段内连续唯一）+ `ts` + `type` + `payload`。

## 三、存储格式与滚动

```
data/event_logs/<session_id>/<segment_seq>.jsonl   # 多段目录（滚动后）
data/event_logs/<session_id>.jsonl                 # 单文件（滚动前，兼容）
data/event_logs/_backup/<ts>/                      # 迁移/退役备份区
```

滚动触发（`EVENT_LOG_ROTATE_*`）：大小阈值（默认 10MB）/ 天数（默认 30）/ 会话结束。
跨段重放逐字节一致；归档段只读。

## 四、生命周期与 CLI

| 命令 | 用途 |
|:---|:---|
| `event-inventory` | 只读盘点（哈希+mtime 验证，文件零修改） |
| `event-migrate` | 存量 session JSON → 事件日志（先备份；幂等二次迁移 0 迁移） |
| `event-verify` | 重放视图与源逐字段对账（差异如实标注） |
| `event-rollback` | 备份区逐字节恢复（可选 `--remove-events`） |
| `event-retire` | 三套存储退役：备份 → 对账 → 归档 session/action_trace → 切读路径（对账全过才切换） |
| `event-retire-rollback` | 退役回滚（读路径切回） |
| `event-rotate-status` | 段清单 |
| `event-hooks` | 过滤钩子管理（list/test） |
| `session-fork` | 会话 fork（事件日志物理复制继承） |

## 五、配置

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `EVENT_LOG_ENABLED` | 1 | 总开关（0=事件写入零行为） |
| `EVENT_LOGS_DIR` | 空 | 目录覆盖（空=从 data_dir 派生） |
| `READ_PATH_SOURCE` | session_json | 读路径分派（session_json / event_log replay 重建） |
| `EVENT_LOG_ROTATE_BYTES` | 10485760 | 滚动大小阈值（0=禁用） |
| `EVENT_LOG_ROTATE_DAYS` | 30 | 滚动天数阈值（0=禁用） |
| `EVENT_LOG_ROTATE_ON_SESSION_END` | 1 | 会话结束时滚动 |
| `EVENT_HOOKS_CONFIG` | 空 | 钩子链配置（filter/desensitize/transform；空=零行为） |

## 六、使用指南

**新项目/新会话**：默认开启即可（写入零行为可关）。无需迁移。

**存量数据启用事件溯源**：
1. `event-inventory` 盘点现状（只读）
2. `event-migrate` 生成事件日志（自动备份）
3. `event-verify` 对账（差异如实标注；活跃会话的并发写差异非缺陷）
4. 稳定后可选 `event-retire` 退役旧存储（对账全过才切换；`READ_PATH_SOURCE=event_log`）

**回滚**：任何一步不满意 → `event-rollback`（或 `event-retire-rollback`）逐字节恢复。

**过滤钩子**（`EVENT_HOOKS_CONFIG` 指向 JSON 配置）：按 priority 升序执行
filter（丢弃）/ desensitize（脱敏）/ transform（转换）；异常 fail-open 不阻断；
审计 `_hook_audit.jsonl` 不含原始 payload 敏感内容。

## 七、设计保证

- **fail-open**：事件写入失败只 warning，不阻断主循环（AI 发挥不受影响）
- **并发安全**：flock 锁内"读最后有效 seq → 分配 → 追加"（90 行并发测试 seq 唯一连续）
- **对账可证**：`event-verify` 逐字段比对；`event-retire` 对账全过才切换（不一致不退役）
- **可回滚**：迁移/退役前自动备份，逐字节恢复
