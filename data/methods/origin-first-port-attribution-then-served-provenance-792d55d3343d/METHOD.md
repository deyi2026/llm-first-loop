---
method_id: origin-first-port-attribution-then-served-provenance-792d55d3343d
name: origin-first-port-attribution-then-served-provenance
description: 用户报告『某个 localhost URL 打开报错(如 401+JSON 错误体)』且本地存在多个候选服务/仓库时，先回答『谁在监听该端口』(lsof+ps)，而不是在本地文件里搜错误字符串或 grep 当前仓库源码；归属确认后沿服务方产物链推进：页面 HTML→其引用的 JS bundle→bundle 中错误文案对应的 API 端点→curl 复现精确错误体→服务配置中的鉴权凭据→带凭据重放验证→在 bundle 中查客户端凭据存储键并给出修复。本例按此路径可省去全局 search_files、无关仓库 grep 与两次超时。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a962d90b-199e-4a0c-af2f-3ce28b719bfb:0:9bc29a4aae0ddf61ed78
evidence_refs: learning:learn:b72bf007ab46
created_at: 2026-09-22T23:27:49.627511+00:00
updated_at: 2026-09-22T23:27:49.627511+00:00
---
## Trigger
用户以具体 URL/端口报告运行时 HTTP 故障（401/5xx + 响应体），环境中存在多个可能归属的服务（独立桌面应用、其他项目 webui、本仓库 dev server），无法默认该端口属于当前工作目录的项目

## Discriminator
报错文本本身是 live 服务器返回的 HTTP 状态码+响应体，且锚定在明确 origin 上——这意味着第一未知量是『端口归属进程』而非『哪个本地文件含此字符串』；随后 curl 该 URL 返回的页面标题/指纹与当前仓库名不符，这一当时已可观察的事实进一步排除『grep 本仓库 webui 源码』这一跳

## Short path
- 未知量=谁在服务该端口：lsof -iTCP:<port> -sTCP:LISTEN + ps 查命令路径，确定归属进程（本仓库 dev server / 独立应用 / 外部服务）
- 若归属非本仓库：读该进程的用户级配置目录（如 ~/.<app>/ 下的 toml/json），并 curl origin 取 HTML；未知量=服务方前端资产与配置在哪
- 在 HTML 引用的 JS bundle 中定位错误文案字符串，得到失败的 API 端点；未知量=哪个请求在返回 401
- curl 该端点复现用户报告的确切错误体；未知量=归因是否成立
- 在服务配置文件中找鉴权字段（如 adminToken），按 bundle/文档提示的请求头重放请求；未知量=服务本身是否健康、正确凭据能否放行
- 在 bundle 中查该凭据的客户端存储键（如 localStorage 的 admin/web token 键），给出可执行修复（UI 设置或控制台写入）后停止

## Stop conditions
- 端口归属进程已确认，且无凭据请求复现用户报告的确切错误、带正确凭据请求返回 200（证明服务端健康、问题在客户端凭据缺失/失效）
- 已给出客户端恢复凭据的具体途径后，不再继续枚举 bundle 或配置中的无关字段
- 若端口探测发现是非 HTTP 的基础服务（数据库/缓存等），终止本路径转向该服务日志

## Verification
- 无凭据请求的响应体与用户报告逐字一致；带凭据同端点请求返回 200 且数据结构正常
- 结论中的失败端点与凭据存储键，能在服务方前端 bundle 中找到对应的调用代码与读写代码

## Counterexamples
- lsof 显示监听进程就是本仓库 dev server：第一跳应转为 grep 本仓库源码，本方法仅保留端口归属确认这一步
- 用户报告的是文件/构建日志中的错误文本而非 live URL 故障：字符串搜索才是正确起点
- 端口属于知名基础服务（数据库/消息队列等）：跳过前端 provenance 链，直接查该服务日志与配置
- bundle 强混淆或文案按 i18n key 拆分导致错误字符串搜不到：回退到浏览器网络面板或端点列表枚举复现
