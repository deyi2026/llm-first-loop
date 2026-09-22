# SPEC：service_control 准入屏障与重启链路修复包 v1

| 项 | 值 |
|---|---|
| 状态 | draft-for-review（事实已核验，方案待人工评审） |
| 定稿时间 | 2026-09-22 08:11 本地（00:11 UTC），会话 fc0ed66c |
| 事实核验窗口 | 2026-09-22 00:00–00:11 UTC（代码行号、回执文件、audit 日志、进程状态） |
| 影响代码 | `src/llm_loop/runtime/service_control.py`、`scripts/restart_mirror.sh`、runbook 文档、告警/审计层 |
| 部署基线 | worktree `deploy-p0a-gen63-20260922` @ `2ff8efb0b`（含 PR #61）；live 已运行 gen63，stable 回执停在 gen62 |

---

## 1. 背景与事故时间线

2026-09-22 晨间的"消息持久化排队不解除"表象，经核验为多个独立缺陷在同一时间窗口叠加。时间线（UTC；本地 = UTC+8）：

| 时刻 | 事件 | 证据 |
|---|---|---|
| 09-14 | knowledge health 守卫上线：legacy/canonical store 分叉时 fail-closed 拒绝 | 守卫逻辑 |
| 09-21 03:58 | 知识库（experiences/、data/methods/）进 git 跟踪（87a971ade）；此后干净部署 worktree 自带 legacy store 快照 | git log |
| 09-21 03:55 | cli 宿主进程（pid 13872）启动，此后未重启，跑旧代码 87a971ade | process_versions |
| 09-21 07:33 | 部署预检 aborted：`code_root_source=env-residue`，指向 `compaction-merge-20260916` 残留 | data/audit/restart_preflight.log |
| 09-21 11:52 | gen60 restart（svc-af12055…）失败：执行前 binding 校验，desired 87a971ade ≠ actual b735e0d6f，worktree dirty；正常转 failed，无 keep | svc-af12055…json |
| 09-21 22:48（本地 06:48） | gen63 restart（svc-089833…，mcp-console-p0a-gen63-deploy）失败：`restart_mirror rc=1`，knowledge 预检拒 dual-root 分叉；action 终态 failed，屏障 keep | svc-089833…json；service_control.py:1351-1360 |
| 09-22 07:45 | 操作员在两份 .env 显式补 `EXPERIENCES_DIR`/`METHODS_DIR` canonical 绑定；knowledge_health 转 healthy | 主根 .env:203-204 + worktree .env:4-5 |
| 09-22 07:47 | 操作员走脚本直连路径重启成功，gen63 live 上线；**不写 durable 回执、不清理旧 action 屏障** | stable 回执仍 gen62 |
| 09-22 07:49 | 用户消息撞屏障，收到持久化排队回执（svc-0898…） | 会话记录；actions 目录 mtime 停在 07:01 |
| 09-22 07:51 | 屏障目录被第三方清空（force_release 与 rm 不可区分，无审计留痕）；排队窗口实际约 2 分钟 | service-control-barriers/ 空目录；全仓无其他变动 |

**定性修正（相对最初叙述）**：
1. 屏障未释放不是"失败路径漏写"，而是**刻意的 fail-closed 遇上失明的失败语义**——脚本已落带阶段标记的 receipt（`knowledge_preflight_failed` 等），worker 只消费 rc、不读 receipt，无法区分"预检失败（零物理副作用）"与"中途失败（stop 可能已发生）"，于是统一 keep。§8.3 docstring 本身要求 "release when the transition proves no physical side effects started"——证明文件已存在，控制面没消费。
2. gen63 重启失败的根因是**两条各自正确的规则的组合缺陷**：knowledge 守卫（拒绝静默选择 store 赢家）× 知识库进 git（干净 worktree 必带 legacy 快照）⇒ dual-root 部署必触发分叉。gen63 是知识库进 git 后第一次 dual-root 部署。守卫无错，缺的是 runbook 未写 operator 显式声明出口。

## 2. 已核验事实（F 系）

- **F1** `service_control.py:1351-1360`：`rc != 0` 显式 `release_barriers="keep"`，注释写明"物理脚本已执行：停止可能已发生，屏障按 §8.3 fail-closed 保留，恢复路径是操作员覆盖 CLI"。
- **F2** `restart_mirror.sh:816-855`：precheck 失败分支严格串行——`_write_receipt <target> "1" "<标记>"` 后立即 `exit 1`，任何 `_stop_*` 调用都在其后 ⇒ 四个 precheck 标记（`webui_artifact_preflight_failed` / `service_control_binding_failed` / `active_run_precheck_failed` / `knowledge_preflight_failed`）可证明**零物理副作用**。带 `port=`/`web_stopped=` detail 的 receipt 与无 receipt 一律可能有副作用。
- **F3** `service_control.py:1411-1414`：`release_barriers` 按服务粒度释放的机制已存在并已投入使用。
- **F4** `service_control.py:431-502`：`accept_restart` 遇屏障冲突直接抛拒绝、不建 action 文件 ⇒ 准入拒绝零持久化痕迹。
- **F5** `service_control.py:368`：`_reap_stale_waiting_actions_unlocked` 只回收 waiting 态超时动作；**终态 failed + keep 不在任何回收路径上**。
- **F6** `service_control.py:1322-1335`：gen60 型失败走执行前 binding 校验，正常转 failed 无 keep ⇒ 反向坐实 rc≠0 分支是唯一屏障泄漏口。
- **F7** `restart_mirror.sh:852-878`：restart 作用域仅 web/feishu/learning；执行 service_control 的 cli 宿主不在作用域内。
- **F8** 释放竞态：`_mark_action`→`update_action` 走 store lease（`service-control.lock` + atomic JSON），failed 转换与屏障释放在同一临界区串行 ⇒ 内生路径安全；07:51 的清除是外生绕锁。
- **F9** 混跑兼容：脚本先升——旧 worker 不读 receipt，行为不变；worker 先升——旧脚本失败无 receipt→keep，行为不变；回滚=回退 worker。风险单向收敛。
- **F10** `_knowledge_preflight`（restart_mirror.sh:776 附近）已有用 `env -u` scrub DATA_DIR 系环境变量的先例，可照搬至根解析层。

## 3. 问题清单（P 系）

| # | 问题 | 严重度 | 证据 |
|---|---|---|---|
| P1 | rc≠0 无条件 keep + receipt 不被消费，"预检失败（无副作用）"与"中途失败（有副作用）"不可区分 | P0 | F1/F2 |
| P2 | 终态 failed + keep 的屏障无租约、无 TTL、无回收方，release 仅认 owner | P0 | F5 |
| P3 | 外生屏障清除零审计：force_release 与 rm 不可区分（07:51 事件） | P1 | F8 |
| P4 | 直连重启成功不写 durable 回执：stable 停 gen62，identity 视图长期报"未达期望代" | P1 | 时间线 07:47 |
| P5 | runbook 缺 dual-root store 绑定步骤（EXPERIENCES_DIR/METHODS_DIR 仅出现在 api.md 配置表），gen64 原样复现 | P0 | docs 全文搜索 |
| P6 | cli 宿主进程不在 restart 作用域：gen63 线 pid 13872 跑 09-21 03:55 的 87a971ade，code_current=false，workspace_dirty=true——**不重启宿主，R1/R3 即死代码** | P0 | F7 |
| P7 | 准入拒绝零留痕：撞墙几次、谁在撞，事后无从知晓 | P1 | F4 |
| P8 | 失败动作积压不过期：gen60 svc-af12055 至今占"失败待处理"投影位，早被 gen63 live 取代 | P2 | pending_actions 回执 |
| P9 | ambient CODE_ROOT env 残留污染预检（07:33 aborted 根因，指向 compaction-merge-20260916） | P1 | audit 日志 |

## 4. 修复项（修订版，6 项）

### P0

**R1｜worker 消费 receipt**（←P1/P2）
- `rc≠0` 时读取 `_write_receipt` 落点：命中 4 个 precheck 标记（F2 白名单）→ `release_barriers=release`（机制已在 F3 存在）；其余标记 / 无 receipt / **receipt 存在但解析失败** → keep。
- 测试：四标记矩阵 × 三分支（release / keep / 解析失败 keep），落 `tests/unit/test_service_admission_barrier.py`（现无此用例）。

**R2｜gen64 部署序列**（←P5/P6）
1. 显式重启 cli 宿主进程，验收 `code_current=true`；
2. runbook 补 dual-root store 绑定步骤（两份 .env 的 `EXPERIENCES_DIR`/`METHODS_DIR` canonical 声明）；
3. 部署预检校验 store 配置键存在且可写，缺失即 fail。

### P1

**R3｜可观测闭环**（←P3/P4/P7）
- 告警四条：① live/stable 回执代差；② 终态 action 仍残留屏障；③ 屏障目录发生非 action 驱动的变动；④ waiting 非终态超时。
- `force_release` 强制 reason + append-only 审计；
- 准入拒绝写 append-only log（不建 action 文件，避免污染 reaper 的 waiting 语义）。

**R4｜env 卫生**（←P9）
- 根解析层拒绝并告警 ambient CODE_ROOT 残留；实现照搬 `_knowledge_preflight` 的 `env -u` scrub 先例（F10）；顺带清理 `compaction-merge-20260916` 残留源。

### P2

**R5｜失败动作 supersession**（←P8）：新代 succeeded 后将旧代 failed 标记 superseded，或投影仅显示 ≥ 当前 desired 代的动作。

**R6｜identity 视图自动探测 live 代**（←P4）：标记 stale 回执。采用探测方案（只读），不强迫直连路径背负 durable 写入义务。

## 5. 设计裁决记录（拷问 A–E）

| 疑点 | 裁决 |
|---|---|
| A. receipt 写入时序与信任边界 | 白名单从 1 个标记扩到 4 个（F2 严格串行证明零副作用）；补"解析失败→keep"约束 |
| B. 孤儿屏障与排队饥饿 | reaper 已覆盖 waiting 态（F5）；真正泄漏源是终态 failed+keep——恰好 R1 堵住唯一泄漏口；reaper 触发条件（超时阈值/租约重入）落地时核实 |
| C. 07:49 排队动作终态 | 准入即拒绝、零持久化（F4）→ 引出 P7，并入 R3 |
| D. 释放竞态 | 内生路径同临界区串行安全（F8）；要堵的是外生绕锁 → R3 审计 |
| E. 混跑兼容与回滚 | 双向安全、回滚单向（F9） |

## 6. 实现约束

- `_write_receipt` 的确切路径契约：脚本与 worker 两侧共享常量，禁止靠路径猜测发现。
- reaper（service_control.py:368）触发条件需在 R1 落地时核实，决定 R3 第④条告警是否已有兜底。

## 7. 部署顺序与回滚

**顺序：脚本 → runbook → cli 宿主重启（最后）。** 宿主重启必须收尾，使其一次性吃进全部改动。

**回滚：回退 worker（cli 宿主）。** 混跑期任一顺序行为均等价于现状（F9），风险单向收敛。

## 8. 验收清单

- [ ] R1：四标记矩阵 × 三分支单测通过（test_service_admission_barrier.py）
- [ ] R2：gen64 部署后 cli 宿主 code_current=true；预检对缺失 store 键 fail
- [ ] R3：四类告警可触发；force_release 无 reason 被拒；准入拒绝在 append-only log 可查
- [ ] R4：注入 ambient CODE_ROOT 时预检拒绝并告警
- [ ] R5：gen60 svc-af12055 不再出现在活跃投影
- [ ] R6：identity 视图显示 live gen 且 stale 回执有标记
