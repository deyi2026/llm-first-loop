---
method_id: resolve-target-locally-before-broad-web-scan-36eb89e276c5
name: resolve-target-locally-before-broad-web-scan
description: 当用户以所有格/语境指称（如“我们的仓库”）指向某实体时，先读取本地权威来源（git remote、config、manifest）钉死精确标识符/URL，再让浏览器直达该 URL 做验证；宽大外部页面只用于最终确认，不用于身份发现。验证取最轻信号（URL/标题），避免对巨型页做全量 DOM 快照；观察通道报连接级错误（ConnectionClosedError）时立即换独立轻量通道而非继续轮询。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:501:c0c25fcf1259809b499c
evidence_refs: learning:learn:23d6b1b29180
created_at: 2026-09-18T03:27:37.909047+00:00
updated_at: 2026-09-18T03:27:37.909047+00:00
---
## Trigger
用户要求在宽大的外部页面上找“我们的 X”（仓库/网站/账号等），而 agent 在同一环境可读取定义该实体身份的本地权威元数据（如工作目录的 git remote），外部入口页本身巨大且无结构化索引。

## Discriminator
用户所有格措辞（“我们的仓库”）本身蕴含目标唯一且已知，且 agent 有 shell/文件权限可在一步内读到 git remote 之类的真值——该事实在第一轮即已存在，足以把“在 GitHub 上找仓库”从开放搜索问题缩成“验证 1~2 个确切 URL”，无需扫描任何宽页面。

## Short path
- 先（或与导航并行）在工作目录跑一步本地权威查询（如 git remote -v），钉死“我们的仓库”的确切 URL 与候选集（含 legacy remote）
- 浏览器直接导航到钉死的 URL：一步同时完成“打开 GitHub”与“找到我们的仓库”，不经过首页浏览
- 验证用最轻观测：URL/ready 谓词等待，或浏览器调试协议的 HTTP 页面列表（如 CDP /json/list）读 URL+标题，不对巨型页做全量 DOM+AX 快照
- 若观察通道报连接级错误（ConnectionClosedError ≠ 谓词未满足），停止轮询等待，改用独立轻量通道（HTTP 端点）完成同一验证
- 已加载 URL/标题与本地推导 URL 一致即输出身份与证据链，停止

## Stop conditions
- 浏览器当前 URL 与页面标题和本地权威来源推导出的 URL 一致
- 本地元数据缺失，或多个 remote 无法消歧且用户未给线索 → 停止并列表候选/询问，而不是转为扫描 GitHub
- 验证通道受物理限制（如快照超出 websocket 单帧上限）且无轻量替代通道 → 报告已验证事实（URL 已加载）与通道限制后停止

## Verification
- 将浏览器当前 URL/标题（页面列表或 URL 谓词）与本地来源推导的 URL 交叉核对
- 确认无登录重定向（URL 不含 login）作为可访问性旁证，而非身份证明
- 通道报错时先区分错误类型（连接级失败 vs 谓词未满足）再决定重试还是换通道

## Counterexamples
- 机器上没有该实体的本地克隆/元数据（“我们的仓库”只在远端存在）→ 本地真值不可得，浏览用户/组织页做发现才是正路
- 本地 remote 与浏览器登录账号冲突（remote 指向个人 fork，“我们的”实际指组织仓库）→ 本地来源非当前权威，需用户确认
- 任务目标就是宽页面本身（如“看看我们 GitHub 首页上有什么”）→ 全页读取是任务而非弯路
- 目标页面很小、快照成本低 → “最轻验证通道”规则无增益，直接快照验证即可
