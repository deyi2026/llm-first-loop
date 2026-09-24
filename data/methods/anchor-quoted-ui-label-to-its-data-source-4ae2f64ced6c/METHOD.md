---
method_id: anchor-quoted-ui-label-to-its-data-source-4ae2f64ced6c
name: anchor-quoted-ui-label-to-its-data-source
description: 当用户逐字引用产品 UI 上的计数/标签/文案并追问其行为原因时，把该字面量当作 provenance 锚点：先用精确字符串搜索定位渲染该文案的前端组件，再沿组件的数据请求边（fetch 端点+参数）走到后端 route 读计数口径；持久化/去重类子问题则分流到已确认的唯一写路径（如 save_candidate→store）去读，而不是先做跨前后端的全库内容搜索或按概念枚举文件名/猜文件类型（前端实为 .tsx 却搜 *.js 这类死胡同即可避免）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:2344:92caa11a085b5c0d92a3
evidence_refs: learning:learn:6e7890005e89
created_at: 2026-09-24T04:49:26.846784+00:00
updated_at: 2026-09-24T04:49:26.846784+00:00
---
## Trigger
用户问题中逐字出现了产品 UI 可见的指标、状态词或错误文案（如面板上的计数、状态标签），并询问该数字/行为为何如此变化；代码库同时包含前端与后端源码。

## Discriminator
t0 即存在的事实：用户消息本身包含被引用面板的逐字文案（具体标签与数值），该字面量可直接定位其渲染组件；同时首轮搜索已确认系统存在唯一写路径 save_candidate，足以把『去重/重复生产』类子问题收窄到 store 与 reflection payload 两处，无需全库枚举。

## Short path
- 对被引用标签做精确字符串搜索（优先前端源码范围）→ 定位渲染组件；未知量：这个数字由哪个组件渲染、从哪个 API 拉取、带什么参数
- 读该组件，确认计数字段（如 counts.saved）与 fetch 调用及 limit 参数 → 得到后端端点名；未知量：计数在后端何处、按什么口径聚合
- 读该端点的 route handler：counts 在 recent_jobs(limit) 窗口内按 state 统计 → 直接回答『为何有增有减』（滚动窗口而非累计，卡未删除）
- 去重子问题沿已确认唯一写路径读 store：method_id = name-slug + sha256(body) 截断，同 id 已存在即返回旧记录 → 仅字节级幂等、无语义去重
- 读 reflection payload 构造，核对是否注入已有方法池 → 回答重复生产与 token 浪费；三个未知量均有权威代码出处后停止

## Stop conditions
- 被引用计数的数据源与聚合窗口语义已由定义该端点的同一文件直接证实
- 去重语义已从唯一写路径的 id 生成逻辑中读到，而非凭函数名推断
- 重复生产判断已核对反思 payload 是否包含已有方法池信息

## Verification
- 确认精确命中的组件确实渲染目标计数（如 counts.saved），而非同短语在无关模块（聊天流式提示）中的假阳性出现
- 计数聚合逻辑读自后端端点实现本身，未用前端展示反推
- 幂等/去重结论引用 method_id 计算所在代码行；token 浪费结论引用 payload 组装处可见字段

## Counterexamples
- 问题只涉及存储/去重语义且用户未引用任何 UI 文案 → 应直接从唯一写路径/store 出发，UI 锚点方法无增益
- 被引短语是高频常用语（如『已生成内容』同时出现在流式聊天模块）→ 精确搜索大量假阳性，必须先验证命中组件确实渲染目标计数再跟随
- 前端仅有编译产物、源码不在仓库 → 标签搜索无法定位渲染组件，应回退为后端 API/路由枚举
