---
method_id: resolve-possessive-referent-via-local-ownership-source-before-portal-bro-e8a525dafdb8
name: resolve-possessive-referent-via-local-ownership-source-before-portal-browsing
description: 用户请求含未解析的所属指称（"我们的仓库"）时，门户首页这类宽表面结构上无法解析它。先廉价确认门户页性质：若只含通用内容且投影超大截断，立即停止页面内翻找，改用环境内编码所有权的来源（当前项目 git remote / 配置）解析出确切地址，再让浏览器深链直达。验证阶段若感知通道报传输层错误（ConnectionClosedError / 1009 message too big），不重试重快照，改用最轻旁道（CDP /json/version 探活、/json/list 取 URL+标题）确认导航结果；本地来源与浏览器已加载页面身份一致即停。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:501:c0c25fcf1259809b499c
evidence_refs: learning:learn:23d6b1b29180
created_at: 2026-09-18T03:27:16.730388+00:00
updated_at: 2026-09-18T03:27:16.730388+00:00
---
## Trigger
用户目标含未解析的所属/相对指称（"我们的/我的/我们在用的 X"），而当前到达的是不编码该所有权的宽表面（门户首页、公共目录、全站搜索）；或浏览器感知通道在超大页面上报传输层错误（连接关闭、帧超限）。

## Discriminator
门户页 snapshot 只含与目标无关的通用内容（营销/导航链接），且投影被明确报告为超大且截断——该页结构上不可能回答"哪一个属于我们"；此时指称只能在所有权编码源（本地 git remote、项目配置、会话上下文）中解析，页面内继续翻找不缩小任何未知量。

## Short path
- 识别用户话语中的未解析指称（"我们的仓库"），明确未知量=该指称的确切 URL；对门户页只做一次廉价性质确认（标题/一次 snapshot），不逐段翻找内容。
- 观察到门户页为通用营销内容且投影超大截断 → 判定页面内搜索无法缩小"哪个仓库"，停止 search_evidence/逐段 hydration，转向本地所有权源。
- 在环境内运行最小所有权查询（如 git remote -v），得到唯一候选地址 <host>/<owner>/<repo>。
- 浏览器直接深链该 URL；未知量收窄为：地址是否可达、是否即用户所指。
- 若感知通道报 ConnectionClosedError/1009 frame too big：不重试重快照；先探 CDP /json/version 排除浏览器崩溃，再用 /json/list 取页面 URL+标题验证导航是否成功。
- 本地 remote 与浏览器已加载页面标题一致 → 事实已被两个独立来源验证，停止并汇报（附通道机械限制说明）。

## Stop conditions
- 指称地址已由本地所有权源解析，且轻量旁道显示浏览器已加载同 URL、页面标题含 owner/repo。
- 本地无任何所有权源（无 git、无项目配置）→ 停止本地解析，转页面内搜索或直接询问用户。
- 旁道 /json/list 已给出目标 URL+标题 → 不再重试重快照，也不再继续扩诊断分支。
- 确认感知失败为通道机械限制（帧超限）而非页面故障 → 停止归因排查。

## Verification
- 对比本地所有权源输出的 URL 与旁道页面清单中的 URL/标题完全一致。
- 用 CDP /json/version 正常响应排除浏览器/链路整体崩溃，确认失败仅限重快照通道。
- 最终汇报中两个独立来源（本地 remote + 浏览器已加载页面）互相咬合，无单点证据。

## Counterexamples
- 用户已给出明确 URL 或仓库名 → 无指称需解析，直接深链并验证即可，绕道本地 git 反而是多余动作。
- 运行环境无本地上下文（全新 CI、无 git 配置、无用户文件）→ 本地解析不可用，门户搜索或询问用户才是唯一路径。
- 目标页面很小且登录后直接列出"你的仓库" → 读页面本身即最短路径，本地绕道不缩短搜索。
- 感知失败是瞬态超时且一次重试即成功 → 应按瞬态错误重试，不应固化切换旁道。
