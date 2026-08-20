# 方案：演进建议审批交互重构（Approval UX v2）

> 状态: **方案（待审）** | 2026-08-20 | 覆盖: Web 面板（EvolutionPanel）· 飞书指令 · CLI · 状态机
> 触发: 用户反馈"审批程序不优雅、交互不友好"——现有审批需逐条展开、拒绝无理由、无批量、无影响面预览

## 0. 现状痛点（实证）

| # | 痛点 | 现状（EvolutionPanel.tsx / feishu approval） |
|---|---|---|
| 1 | 列表混排 | 待审批/已处理/已执行全在一个列表，无分类 Tab |
| 2 | 无二次确认 | 展开后"批准/拒绝"按钮直接执行，误点即生效 |
| 3 | 拒绝无理由 | `review(id, "rejected", "")` reason 硬编码空串，拒绝理由丢失 |
| 4 | 无批量 | 多条待审批需逐条展开逐条点 |
| 5 | 无过滤/搜索 | limit=30 截断，长列表难定位 |
| 6 | 无影响面预览 | 审批人看不到改动内容/影响文件，只看到 AI 自述摘要 |
| 7 | 反馈弱 | 执行后仅小字 actionMsg，无状态变化引导 |

## 1. 设计目标

**让审批像"审代码"一样**：一眼看到"改了什么、影响多大"，一键决策（含批量），拒绝留痕，状态全程可追踪。

## 2. 交互设计（三层入口统一体验）

### 2.1 Web 面板（主入口，重构 EvolutionPanel）

**A. 分类 Tab**（替代混排）
```
[🔔 待审批 (n)] [✅ 已接受] [❌ 已拒绝] [⚙ 已执行] [全部]
```
- 待审批默认选中、未读数 badge
- 各 Tab 独立滚动，不再 30 条截断（后端支持分页/游标）

**B. 详情卡片（展开后）**——"审批工作台"而非裸按钮

```
┌─ EVO-20260820-5bf342ae  [P2] [待审批]  ────────────┐
│ 摘要: 单轮输出触发上限被截断…                        │
│ ── 影响面 ──                                       │
│  · 涉及: engine.py 流式输出 / config.py            │
│  · 证据: eval:SE-xxx（评估关联）                    │
│  · requires_human: ⚠ 涉边界                         │
│ ── 决策 ──                                         │
│  [✅ 批准]  [❌ 拒绝]  [📝 理由输入框]              │
│  · 批准后自动执行: 是/否（EVOLVE_LOCAL_EXEC 分级）   │
│  · 操作记录: 执行于/核验于 时间戳                    │
└────────────────────────────────────────────────────┘
```

**C. 交互细节**
- **二次确认**：点"批准/拒绝"弹确认（批准：显示将执行的动作；拒绝：理由必填）
- **拒绝理由必填**：无理由拒绝禁止提交（留痕）
- **批量**：待审批 Tab 支持勾选多条 → 批量批准（含理由模板）
- **影响面自动提取**：后端在 list 接口附加 `impact_hint`（从 content 提取文件/模块引用），前端卡片展示
- **diff 预览**：若建议关联了实际改动，展开可选"查看 diff"（后端只读返回）

### 2.2 飞书指令（对齐 Web 能力）
```
审批列表 / 批准 EVO-xxx / 拒绝 EVO-xxx 理由：必填
+ 批量: 批准全部 待审批（逐条确认）
+ 详情: EVO-xxx 详情（返回影响面+证据）
+ 理由补录: 若已拒绝无理由，可 "补录理由 EVO-xxx 理由：…"
```

### 2.3 CLI（evolve-review 增强）
```
evolve-review list            # 分类列表
evolve-review show <id>       # 详情+影响面
evolve-review approve <id>    # 确认交互
evolve-review reject <id> -r <理由>   # 理由必填
evolve-review approve-all     # 批量（逐条确认）
```

## 3. 后端改动（支撑交互）

| 改动 | 说明 |
|---|---|
| `GET /api/v1/evolution/list` 加 `status` 过滤 + `impact_hint` 提取 | Tab 分类 + 影响面预览 |
| `POST /api/v1/evolution/review` 拒绝时 reason 必填校验 | 留痕 |
| 新增 `GET /api/v1/evolution/diff?id=`（只读，若建议有 actions/diff） | diff 预览 |
| 批量端点 `POST /api/v1/evolution/review-batch` | 批量决策 |
| `EvolutionSuggestion` 增加 `impact_files` 字段（提交时提取） | 影响面结构化 |

## 4. 状态机增强（审批透明度）

```
pending_review ──approve──▶ accepted ──auto_exec──▶ executing ──▶ executed
      │                        │                        │
      │                        └─(人工执行)────────────▶ executed
      ├──reject(必填理由)──▶ rejected（含 rejected_reason 字段）
      └──(requires_human)──▶ 强制人工（AI 不可自动，已有）
```

- `rejected_reason` 字段：拒绝理由持久化（现无此字段，拒绝即丢）
- `reviewed_at`：审批时间戳（现仅 executed_at/verified_at，缺审批时刻）

## 5. 实现路径（MIRROR 协议）

```
镜像实施（后端 list/review 增强 + EvolutionPanel 重构 + 飞书/CLI 对齐）
→ 镜像验证（Web 审批全流程 + 飞书指令 + 拒绝留痕 + 批量）
→ 提交审批 → 主区同步 + 全量回归 → 重启生效
```

### 验证清单
- [ ] Web：Tab 分类、拒绝理由必填、二次确认、批量批准
- [ ] 飞书：批准/拒绝带理由、批量、详情
- [ ] CLI：evolve-review 增强命令
- [ ] 拒绝后 `rejected_reason` 落盘可查
- [ ] 既有 151 测试无回归

## 6. 风险与取舍

| 风险 | 对策 |
|---|---|
| 批量批准误操作 | 逐条确认 + 批量仅限同优先级 |
| impact_hint 提取不准 | 后端启发式（文件路径/模块名正则），失败降级为摘要 |
| diff 预览泄露敏感 | 只读端点 + 本地 web 白名单（与现有审查一致） |
| 改动面大 | 分两批：批 1 = Tab 分类+拒绝理由+二次确认（交互核心）；批 2 = 批量+diff 预览 |

## 7. 期望效果

- 审批从"逐条点按钮"变为"看影响面 → 决策 → 留痕"三步
- 拒绝理由可追溯（`rejected_reason`），AI 可据理由改进重提
- 待审批未读提醒（badge）+ 分类，长列表不再淹没
- 飞书/Web/CLI 三端体验一致
