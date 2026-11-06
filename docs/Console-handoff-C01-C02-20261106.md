# C-01 / C-02 移交报告：MCP Console 侧接口修复（LFL 不代修）

日期：2026-11-06（Asia/Shanghai）
来源：`docs/promotion/LFL_Computer_Browser_Audit_Requirements_Design_2026-11-06.md` v1.1 §3.9/§3.10/§5.7/§405/§408
审计证据级别：A（当前插件现场复现）；审计基线 Console `0.1.589`。

## 问题描述（审计原文摘要）

**C-01（P2）开页返回错误层级的句柄**：`browser_open_page` 结果只含原始 `tabId`/`windowId`，无工具契约所述 `page_id`；把 tabId 当 page_id 用得到 "page no longer exists"，经 list-pages 才能映射到正确句柄。

**C-02（P2）标签已关闭后的释放不是完整幂等**：attach→close→`browser_release_debugging` 首次返回 `ok=true` 但 `debuggerReleased=false`、`failedDebuggeeCount=1`、detachErrors 含 "No tab with given id"；第二次才明确 `alreadyReleased`。只看顶层 ok 的调用者会误判。

## 现状声明（诚实边界）

- 审计基线为 Console `0.1.589`；本会话记录 Console 已升级至 **`0.1.593`**，但本 LFL 会话无 MCP Console 工具面，**未能在 0.1.593 上复核** C-01/C-02 是否仍在。
- 请 Console 实现方在 `0.1.593+` 上按下方验收口径复核；若已修复请回执版本号与结果，本报告随之关闭。

## 移交要求（对 Console 实现方，对应审计 §5.7）

1. open-page 在服务端完成 tab→page 注册映射后返回 `profile_id + page_id`；注册未完成则显式 `pending` 并提供等待 handle-ready 的明确方式，不得只给原始 tabId 却报流程完成。
2. 原始 tabId / CDP target ID 仅用于诊断，与可操作句柄明确隔离（当前页面清单含原始 target 字段，与契约「原始 ID 不暴露」不一致，一并核对）。
3. close-page 清除本会话 attachment ownership；release-debugging 把「目标已销毁/已分离」按幂等成功处理，仅真实 detach 失败保留错误。
4. release 顶层 ok 与 `debuggerReleased` 的关系写入 schema；真实部分失败必须结构化可识别，不能让调用者从自然语言错误里猜。
5. 多 profile 必须显式选择，禁止「当前活跃 profile」启发式补齐。

## 验收口径（对应审计 T-13/T-14）

- T-13：open→直接 get-state→locate/action，无需额外 list-pages 取句柄；profile 与 page 不混用。
- T-14：attach→close→release 与重复 release：清理幂等；不存在目标不判为活跃连接泄漏；真实失败可区分。

## LFL 侧适配承诺（修复落地后）

- 若 open-page 返回结构化 `profile_id+page_id`，LFL 接收层（computer_use_*/browser_* 工具封装）适配新回执形状，保持旧形状兼容期并版本化。
- release 语义拆分后，LFL 对 `alreadyReleased/destroyed-as-success` 不再重试；真实失败按错误类别上报。
- Console 与 LFL 各自持有候选与测试，不互用 PASS（审计 §408）。
