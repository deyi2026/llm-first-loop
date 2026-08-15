# Web V2 差异对比文档（对齐 DeepSeek Harness Web 端）

日期：2026-08-15 · 分支：`feature/web-v2` · 挂载：`/ui/v2`（与原版 `/` 并存）

## 1. 背景与目标

llm-first-loop 原有 Web 端（`src/llm_loop/web/`，vanilla JS 零构建）功能完整但视觉/交互与
DeepSeek Harness Web 端（DSH，Vite+React SPA）差距明显。按用户决策重开发全新版本
（React 18 + TypeScript + Vite），**功能逻辑与业务流程对齐原版与 DSH，UI/交互/视觉等效还原
DSH**；原版保留不动，双版本并存，独立分支开发。

## 2. 功能对齐清单（DSH 模块 × 本版本三态）

| DSH 功能模块 | 状态 | 实现 |
|---|---|---|
| ui-conversation（消息流/工具行/思考块/压缩摘要/分支/排队/插话） | ✅ 对齐 | 流式渲染（answer/reasoning/tool_round/done）、思考块默认折叠、工具链折叠+状态chip、代码块 banner+高亮+分块、回到底部、加载更早、乐观清空、等待进度可视化 |
| ui-sidebar（会话列表/新建/搜索） | ✅ 对齐+增强 | 搜索、置顶、两步确认删除、分支（fork→切换）、新会话、来源通道标签、子代理标签、消息数 |
| ui-layout（三栏壳） | ✅ 对齐 | 侧栏\|会话主区\|右侧面板；侧栏/面板可折叠；≤900px 抽屉式 |
| ui-commands + ui-input-trigger（/ 命令、@ 触发） | ✅ 对齐 | `/` 命令面板（new/clear/model+目录选项，点选即执行）；Enter/Shift+Enter |
| ui-model-selection（模型+推理等级） | ✅ 对齐 | 模型下拉（会话级覆盖随请求携带）、模型目录面板（当前标记） |
| ui-theme（亮/暗/跟随系统） | ✅ 对齐 | `data-ds-dark-theme` + `--dsw-alias-*` token 体系（提取自 DSH 运行时 CSS） |
| ui-tool（工具详情/审批） | ✅ 对齐 | 回执状态 chip（成功/失败/已拦截/超时）+ 展开全文；声明侧工具链 |
| ui-message-feedback | ✅ 对齐 | 助手消息 👍👎 → `feedback.jsonl` 审计（后端新端点） |
| ui-subagent | ✅ 对齐 | 侧栏 `subagent_` 会话"子代理"标签 |
| ui-settings（通用/模型） | ✅ 对齐 | 服务/版本/连接 + 模型目录 |
| session-log-export | ✅ 对齐 | 会话头"导出"→ 全量分页 → Markdown 下载（客户端） |
| ui-locale（国际化） | ✅ 对齐 | zh-CN 结构化文案 |
| ui-jobs（后台任务） | ⚠️ 裁剪 | 后端无任务 API，如实占位（阶段 4 标注） |
| ui-cordis / ui-trajectory / ui-permission-presets / ui-agent-preset / ui-deliverables / ui-workspace / ui-workflow-run / ui-goal / ui-plan / ui-skill | ❌ 裁剪 | 后端无对应概念（计划/工作流/目标在 P3 路线，V2 届时可接入）；技能经工具使用 |
| connection/runtime/api-gateway/typert/hmr | ❌ 裁剪 | 后端不必要（SSE 事件 + /health 已覆盖连接态） |

## 3. 与原版（v0.x Web）差异对比

| 维度 | 原版（vanilla JS 9 模块） | V2（React+TS） |
|---|---|---|
| 技术 | 零构建全局函数 | 组件化 + 类型安全 + Vite 构建（dist 由 FastAPI 挂载 /ui/v2） |
| 布局 | 两栏 | 三栏 + 折叠 + 移动端抽屉 |
| 主题 | 固定浅色 | 亮/暗/跟随系统（DSH 同源 tokens，含 shiki 代码配色） |
| 命令 | 文本命令 | `/` 面板（匹配/选项/点选执行/反馈提示） |
| 消息 | 正文+思考+工具折叠 | + 状态chip、反馈、代码块 banner/分块（延续"不折叠"决策） |
| 输入 | 文本框+上传 | + 乐观清空、等待进度（首 token 计时/同会话排队提示）、附件状态气泡 |
| 会话 | 列表+搜索+置顶+fork | + 两步删除、分支切换、子代理标签 |
| 同步 | SSE 刷新（v0.5.6 修复命名事件） | 沿用 + 失联自愈看门狗 + 聚焦即刷（v0.5.6 加固移植） |
| 图片/文档识别 | MiniMax 视觉（404/无视觉） | 团队识别工具优先 + 注册表 multimodal 模型兜底（Kimi 实测可用）+ 防幻觉诚实标注 |
| 导出 | 无 | 会话 Markdown 导出 |

## 4. 后端变更（本分支合入后全产品受益）

- `vision.py`：auto 链（arkcli 工具 → 注册表 multimodal 模型 → 明确报错）；`WEB_VISION_BACKEND`/`WEB_VISION_MODEL` 可配
- `upload_handlers.py`：docx/pdf 走 `arkcli doc-extract` 结构化抽取，本地提取兜底
- `routes.py`：新增 `POST /api/v1/sessions/{id}/feedback`（feedback.jsonl 审计，不侵入会话）
- `providers.json`（本地配置）：kimi 模型标记 multimodal

## 5. 验证记录

- 门禁：pytest **2038 passed** + ruff 0 + pyright 0（分支 CI 全绿）+ Vitest **29/29** + tsc 0 + vite build
- 实测：真实会话 fork/pin 200；上传图片 → Kimi 视觉识别（红/蓝测试图准确描述）；流式协议端到端（reasoning/answer/done）；SSE 命名事件；跨端同步
- 双版本并存：`/`（原版）与 `/ui/v2`（V2）同时可用，后端 API 同源

## 6. 切换方案（待用户确认）

| 方案 | 说明 | 回退 |
|---|---|---|
| A. 保持并存（当前） | `/` 原版、`/ui/v2` V2 | 无需 |
| B. V2 为主入口 | 构建产物同时挂载 `/`（原版静态移至 `/legacy`） | 移回即回退 |
| C. 独立端口 | V2 起独立服务（如 8912） | 停进程即回退 |

推荐 A 观察一段时间（V2 已在真实环境跑工具调用/识别/跨端同步），稳定后按需切 B。
