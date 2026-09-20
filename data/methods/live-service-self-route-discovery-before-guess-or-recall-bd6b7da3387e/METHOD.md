---
method_id: live-service-self-route-discovery-before-guess-or-recall-bd6b7da3387e
name: live-service-self-route-discovery-before-guess-or-recall
description: 验证本地已重启的 web 服务而面板路由未知时，不要先翻 Evidence/Archive 回忆 URL（一次未命中后换源再查），也不要枚举猜测常见路径（/panel、/ui、/dashboard）。服务本身是路由的权威来源：状态输出给 pid，lsof 得 host:port，然后 GET / 跟随重定向，登录跳转的 next 参数直接给出受保护的规范路由，登录页 200 同时证明渲染正常。命令层 curl 可达而 browser 工具 ConnectError 时，判定为运行环境网络隔离，用 curl 完成路由与渲染验证并在结果中说明，不重试 browser。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:1285:db025733ad21a02f3175
evidence_refs: learning:learn:8ec8b98a98f5
created_at: 2026-09-20T17:27:32.673926+00:00
updated_at: 2026-09-20T17:27:32.673926+00:00
---
## Trigger
本地服务已确认在跑（状态输出给出 pid，pid→lsof 得到 host:port），需要验证其 UI/路由，但路由未知或 Evidence/Archive 检索未命中

## Discriminator
服务已在已知 host:port 监听且命令层 HTTP 可达（curl 能拿到状态码）——此时『路由是什么』这个未知量的权威判别来源是服务自身的根路径重定向/登录 next 参数，而非路径猜测或历史检索；goal/状态输出中『页面级实测』类记录只证明路由存在，不给出路由值

## Short path
- 读部署/目标状态：确定验证范围（如仅 web）、pid、git_head/generation 是否匹配——这些由状态输出直接判定，无需另查
- lsof -a -p <pid> 得到监听 host:port，解决『服务在哪监听』
- curl -sL http://host:port/ 跟随重定向：根路径的登录跳转 next 参数给出规范路由，登录页 200 证明渲染正常——解决『面板路由是什么』
- curl 规范路由（未认证）：预期 303→登录，确认路由存活且鉴权生效
- 停止并汇报：所需事实均来自服务自身响应；若 browser 工具对该地址 ConnectError 而 curl 可达，记为环境隔离，以 curl 结论收尾

## Stop conditions
- 状态输出已确认 git_head/generation/pid 匹配，且根路由与规范路由均返回预期重定向/状态码
- 服务自身响应已给出规范路由且页面可达，不再枚举其他候选路径、不再二次检索历史
- browser 连接被拒而 curl 同地址可达：判定环境网络隔离，停止尝试 browser

## Verification
- 最终报告的路由取自服务实际响应（重定向 Location / next 参数），而非猜测或过期记录
- pid、端口、generation 与权威状态输出一致
- 未认证访问规范路由确实触发登录重定向（鉴权未失效）
- 范围外服务（如仍需重启的其他 service）只作附带说明，不擅自扩scope

## Counterexamples
- SPA 对所有路径返回同一 app shell、根路径不重定向：重定向揭示不了路由，需读路由配置或构建产物
- 路由已存在于当前会话 Evidence 或配置文件：直接按记录验证，跳过发现步骤
- 验证目标需要登录后的 DOM/交互行为且 browser 环境确实可达该地址：curl-only 不足，应走浏览器
- 根路径就是 404 的纯 API 服务：无 UI 路由可言，直接验证已知 API 端点
