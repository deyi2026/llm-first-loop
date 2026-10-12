# 实施：演进审批交互批 1（Approval UX v2 · Batch 1）——镜像区

> 状态: **待审批（草案）** | 2026-08-21 | 依据: DESIGN-approval-ux-v2 + grill 拷问 8 项补丁 + 记忆决策"web 端为主、CLI 备用"
> 执行: 镜像 LFL → 验证 → 人工审批 → 主区同步

## 0. 定位（记忆决策对齐）

演进审批/登记**以 web 端（/ui/v2 左侧栏 EvolutionPanel）为主**，CLI/飞书仅备用通道。
批 1 全部落在 Web 面板 + 后端支撑；CLI/飞书增强不入批 1（备用可选，另行评估）。

## 1. 批 1 范围（含 8 项拷问补丁）

| # | 项 | 来源 |
|---|---|---|
| 1 | 分类 Tab（待审批/已接受/已拒绝/已执行）+ 未读 badge | DESIGN §2.1A |
| 2 | 详情卡片：摘要 + 影响面 impact_hint + 决策按钮 | DESIGN §2.1B |
| 3 | 二次确认（批准/拒绝弹确认；拒绝理由必填） | DESIGN §2.1C |
| 4 | **完整内容懒加载**（列表回摘要、详情端点按需取全文） | 补丁 D/Q10 |
| 5 | 影响面预览（提交时落库 impact_files 快照 + 实时 diff 双源） | 补丁 B/Q6 |
| 6 | 审批结果回流 AI（rejected_reason 注入/可见） | 补丁 C/Q9 |
| 7 | **乐观锁 CAS**（review 带 expected_status，冲突 409） | 补丁 B/Q4 |
| 8 | **批量服务端硬校验**（跳过 requires_human + 涉边界禁止批量） | 补丁 A/Q1 |
| 9 | **拒绝理由防护**（长度上限 500 + 转义 + 只追加不覆盖 reason_history） | 补丁 A/Q3+C/Q7 |

## 2. 后端改动（src/llm_loop）

### 2.1 数据模型 introspection/evolution.py
- `EvolutionSuggestion` 增字段（默认值兼容旧记录）：
  - `impact_files: list[str] = []`（提交时从 impact_scope/content 正则提取）
  - `rejected_reason: str = ""`、`reviewed_at: str = ""`
  - `reason_history: list[dict] = []`（补录只追加：{reason, at}）

### 2.2 审批状态机 feishu/approval.py
- `reject(store, evo_id, reason)`：reason 必填校验（空→400）；落 `rejected_reason` + `reviewed_at`；已有理由→追加 `reason_history` 不覆盖
- `approve(store, evo_id)`：落 `reviewed_at`；返回增加 expected_status 供 CAS

### 2.3 Web 路由 web/routes.py
- `GET /api/v1/evolution/list`：加 `status` 过滤参数（Tab 分类）；返回 `impact_hint`（从 impact_files 摘要，失败降级 content 前 120 字）；**content 不再截断 200**（列表只回摘要，全文走详情端点）
- `GET /api/v1/evolution/detail?id=`：返回完整 content/evidence/impact_files（懒加载全文）
- `POST /api/v1/evolution/review`：body 增 `expected_status`（可选，CAS）；拒绝 reason 必填；涉边界项（requires_human）拒绝批量但单条批准需额外确认标志
- `POST /api/v1/evolution/review-batch`：批量端点；服务端过滤 `requires_human=true`（跳过+返回被跳过清单）；逐条独立事务（成功 n/失败 m）
- `GET /api/v1/evolution/diff?id=`：只读；suggestion 校验（存在 + 非 rejected）；无关联改动→404

## 3. 前端改动（webui/src/components/sidebar/EvolutionPanel.tsx）

- 分类 Tab：状态过滤（复用 list?status= 参数）；未读 badge（pending_review 计数）
- 详情卡片：摘要 + impact_hint + 「展开全文」（懒加载 detail 端点）+ 决策按钮
- 二次确认：批准→"将执行 X 动作"确认；拒绝→理由输入必填
- 批量：勾选同优先级非涉边界 → 一次确认 n 条 → review-batch；结果"成功 n/失败 m"刷新
- 409 冲突：提示"已被他人处理，已刷新"并重载
- 涉边界项：批量禁用 + 单条批准额外确认

## 4. 验证清单（镜像）

- [ ] list?status= 过滤正确（四 Tab 计数与状态机一致）
- [ ] 拒绝无理由 → 400；有理由 → rejected_reason 落盘 + reviewed_at
- [ ] 补录理由 → reason_history 追加、原理由保留
- [ ] 详情端点返回全文（懒加载）；列表无 200 截断
- [ ] 乐观锁：模拟并发 review → 后到 409 + 提示
- [ ] review-batch 跳过 requires_human + 逐条独立（半成半败正确）
- [ ] impact_files 提交时提取正确；diff 端点 404 语义
- [ ] 既有 151 测试无回归（PYTHONPATH 隔离）
- [ ] 涉边界项单条批准需额外确认

## 5. 实施流程

镜像实施 → 镜像验证（上表） → 人工审批 → 主区同步 → 重启生效
