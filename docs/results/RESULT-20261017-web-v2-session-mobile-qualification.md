# Web V2 会话切换与移动端稳健性专项（2026-10-17）

## 范围与权威

- 隔离分支：`fix/web-v2-session-mobile-20261017`；基底 main：`41f500ecb92c7aea881d8e15809194187b7b1dd3`。
- 仅修改 Web V2 会话索引/历史请求、手机遮罩，以及会话元数据缓存的固定上限；不改会话真源、LLM/后台 run 语义或取消接口。
- 主工作树存在其他 Agent 的未提交修改，未触碰或重置；不得直接从本结果推断生产已生效。

## 事故事实与边界

1. 生产只读测速：`/api/v1/sessions` 曾耗时约 8.47 秒，另三次约 3.50/3.55/4.37 秒；同期两个会话最近 100 条消息请求约 0.14/0.16 秒。证实会话索引读取是性能嫌疑点，**不证明**全部卡顿来自单一根因。
2. 主工作区约 961 份会话 JSON，约 651 MB，而原会话元数据缓存仅 512 条；超出上限时暖列表仍需重复解析磁盘文件（可由缓存回归机械验证）。
3. 原前端对会话列表无上界等待；多个消费方可同时发出同一请求。历史消息请求在会话切换时没有独立取消，慢链路可能留下过时在途请求。
4. 移动端遮罩转换为语义按钮后存在原生 2px 边框；Chromium 触控视口 320/375/390/430/768px 五尺寸真实 RED 复现，属于可见样式缺陷。

## 隔离候选修改

- 服务端缓存 512 → 2048，保持 mtime/size 校验与有界 LRU，未为快测扩架构基线。
- 会话索引 GET 同范围并发合并；20 秒无响应主动中止并保留既有会话列表；下一次请求可再试。
- 最近历史 GET 15 秒超时；视图会话切换时取消过时请求且忽略迟到响应。该取消仅是 HTTP 观察订阅层，**不调用后端取消运行任务**。
- 手机抽屉增加有名称的关闭按钮、Escape 关闭；屏蔽原生按钮 border/padding/appearance，保留可触控遮罩。
- 新增会话索引超时 RED→GREEN、过时请求终止回归和可重复运行的无生产 API 副作用浏览器 QA：`scripts/qa_web_v2_session_mobile.py`。

## 验证记录

- 浏览器：独立本地 Vite + Chrome 153 无头真实布局/触控模拟。所有 API 请求被本地 synthetic fixtures 拦截；未发送实际聊天、归档、删除或生产变更请求。
- RED：320×568、375×812、390×844、430×932、768×1024 五个移动/平板视口均检出遮罩 2px 原生边框。
- GREEN：上述五个 + 1366×850 桌面共 **6/6 PASS**；包括切会话、遮罩与 Escape、横向溢出、聊天历史滚动与切换后数据归属。
- 会话索引无限等待 RED：在没有 abort signal 的原实现中先失败（`expected undefined to be true`）；添加定时取消后针对性通过。
- 同候选定向前端（包括慢请求取消）**12/12 PASS**；前端完整 Vitest **309/309 PASS（41 文件）**；Python `tests/unit/test_session.py` **36/36 PASS**。
- 原版 `bash scripts/ci_gate.sh --quick` 真正终态 exit 0：Ruff/Pyright 历史债 ratchet **0 新增、修改文件零红**，测试环境声明守卫 PASS，候选 WebUI 构建 PASS，tier0 **319 PASS / 9122 deselected**；此处严格不等同于完整 R9。
- 候选暂存区 `bash scripts/git_security_scan.sh --staged` 对 12 文件 PASS，`git diff --cached --check` PASS。
- QA 结果与截图留在本地忽略目录：`data/web-v2-mobile-qa-20261017/{report.json,viewport-*.png}`。
- 这验证的是 **Chromium 移动仿真**，不是实体 iOS Safari、Android WebView 或真实弱网设备。生产 before/after 延迟改善仍待受控上线后同口径重测；不得从 6/6 UI 功能 PASS 宣称线上性能达标。

## 待放行闸

1. 冻结当前变更指纹并由真正独立的代码 Reviewer 根据 `skills/code-review-gate/SKILL.md` 审阅（RULE-AI-28），有效 PASS 且 P0/P1 均为 0。
2. 审查后对冻结 candidate 跑项目原版 `bash scripts/ci_gate.sh`（完整 R9）；保留退出码/日志/候选指纹，切勿把 Quick 当全量。
3. 与最新 main 再核对交叉文件，独立合并门与生产 Web-only 切换门分别办理；先检查 live session 和期望 generation，不抢占其他 Agent 会话。推送与重启需各自授权和事后 PID/实际资源指纹验收。

**当前结论**：前端移动浏览器功能性检查通过，独立审查与完整 R9/上线仍为待验证；该候选尚不能标记 production GO。
