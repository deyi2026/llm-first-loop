---
method_id: fingerprint-is-not-wiring-verify-before-direct-api-calls-5e2ca480e807
name: fingerprint-is-not-wiring-verify-before-direct-api-calls
description: 当既有报告仅凭『bundle 内可见某库特征』这类指纹级 provenance 断言系统使用某集成（认证/后端），而当前计划要直接调用该集成 API 时，先做一次结构化核验：该集成的域名/配置/凭据是否真的硬编码在产物里。若只命中库代码与用户可配置占位符、凭据形态字符串 0 命中，立即证伪『直接调集成』假设，转为追踪系统自身同源调用点（fetch/axios、register/login/API 路径）并直接探测端点；不要在同一产物上继续更换提取姿势。附：对外部站点写交互脚本前先读工具 schema 确认 URL 白名单。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:94:b8d42d4012b1faee568f
evidence_refs: learning:learn:7bdbbe212603
created_at: 2026-09-18T02:15:26.481362+00:00
updated_at: 2026-09-18T02:15:26.481362+00:00
---
## Trigger
计划直接调用某第三方集成（认证提供方/后端 API），而该集成的存在依据仅是先前分析中的库特征指纹（如『bundle 内可见 supabase-js 特征』），未见实测端点或配置；或需在沙箱内对外部站点做交互探测时。

## Discriminator
三个在 pivot 前已可见的事实：① 报告断言自带指纹级 provenance 限定词（『bundle 内可见 supabase-js 特征』=库指纹，非实测端点）；② 一次 grep 显示集成域名仅出现于库通配符与设置表单占位符（your-project.supabase.co，即用户可配置项）；③ anon key/JWT 形态字符串 0 命中。合起来把『提取硬编码配置』的候选空间缩为『配置不在产物中，须追踪系统自身调用点』。

## Short path
- 读工具 schema 确认可用通道（浏览器 helper 的 URL 白名单是否覆盖目标站）：未知量=用什么通道触达站点
- 读既有报告中关键断言的 provenance（指纹级 vs 实测端点）：未知量=集成是否真实接线
- 一次结构化 grep（集成域名/凭据形态/JWT 模式）：若仅命中库通配符与表单占位符、凭据 0 命中→假设证伪，停止提取尝试
- 转向系统自身调用点：在产物中检索 fetch/axios 与 register/login/chat 的同源 API 路径：未知量=注册实际打哪个端点
- 用普通 HTTP 直接探测该端点并实际提交注册：未知量=有无验证码环节、会话如何建立
- 沿同源调用链实测聊天通道与后端真身，用户问题获得直接响应证据→停止

## Stop conditions
- 系统自身注册/登录端点已被实测响应，认证接线以直接证据解决
- 同一产物上连续 ≥2 次结构化检索均为负（无配置、无凭据、无调用点变体）→ 停止提取，如实报告未知，而非换第 N 种提取姿势
- 用户目标问题已由直接响应证据回答

## Verification
- 实际调用的端点能在产物调用点中找到对应（端点-调用点 provenance 一致）
- 流程断言（有无验证码、会话机制）来自实际提交后的 HTTP 响应，而非报告转述
- 对先前报告中被推翻的断言显式标注修正依据（新旧证据并列）

## Counterexamples
- bundle 内确实硬编码了项目 URL 与 anon key：指纹断言为真，直接调集成 API 即为正确短路径，不应过早放弃
- provenance 是运行时实测（网络日志中实际见到该集成请求）：属实测级证据，可直接采用集成路线
- 目标问题靠静态产物即可回答（路由/SEO/文案类），无需验证认证接线：不做任何 wiring 探测
- 目标站点对当前网络完全不可达（同源端点也探测不了）：只能依赖被动产物，多角度提取成为仅剩手段
