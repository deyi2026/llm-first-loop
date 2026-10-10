---
method_id: clone-first-for-bulk-repo-ingestion-63c81319e94c
name: clone-first-for-bulk-repo-ingestion
description: 当任务是把外部 git 仓库的一批文件/子树/整套 skill 纳入本地工作区时，第一步直接用 git clone --depth 1 把仓库本体落到临时目录，再在本地树上看结构、裁剪、适配；不要先用网页抓取工具去拉 tree/listing API。抓取型工具即使成功也只返回文件名清单，仍需逐文件二次获取；clone 一步得到完整可审计文件树，还能记录源 commit 做出处。仅当目标只是读单个页面、取极少数文件、或源不是 git 仓库时才走 web_fetch 路径。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:0051f593-fc2b-4570-b0f6-2afe09af0b5e:63:491bb7272a4ca503f524
evidence_refs: learning:learn:c2110c572fb4
created_at: 2026-10-10T10:04:46.223778+08:00
updated_at: 2026-10-10T10:04:46.223778+08:00
---
## Trigger
任务要求『纳入/引入/移植/vendor』多个来自 GitHub 等 git 远端仓库的文件、子树或 skill 到本地目录，且尚未发起任何网络获取动作时。

## Discriminator
选第一个网络工具前即可判断任务形状：交付物是整个仓库文件集（用户动词为纳入/吸收，后续计划含入库、裁剪、验证），来源是 git 仓库——这是『批量物化』而非『读取网页内容』；HTTP listing 端点只产出名字不产出内容，天然制造第二阶段逐文件获取，而 git 是该资源的原生协议。此判断不依赖任何抓取失败回执，在第一次网络调用前就成立。

## Short path
- 先核本地目标目录与格式规范（读一个现有同类 artifact 作 frontmatter/结构样例），确认入库约束
- 识别源为 git 远端且需要多文件 → 对每个源 git clone --depth 1 到临时目录，一次命令得到完整树
- 在本地树上检查目录结构、各部分体积与关键文件头部，决定保留与裁剪范围（剔除文档/演示应用/测试等非运行件）
- 读本地加载器/消费方源码确认兼容性约束（如 frontmatter 解析严格度），再复制适配并保留上游 license 与源 commit 出处
- 安装缺失的运行依赖，跑加载器解析与代表性 smoke test（自检/端到端注入用例），通过即停止发现阶段

## Stop conditions
- 所有目标文件已入库并通过加载器解析与功能验证（真实调用或 --self-test / 端到端用例命中）
- clone 失败或被环境禁止（源非 git 仓库、网络策略不允许 git 协议）→ 回退到抓取/归档路径或向用户说明，不反复重试同一 listing URL

## Verification
- 入库文件数与体积和上游树一致（目录数与文件清单核对），并已记录源 commit 作为 provenance
- 本地加载器对每个新条目解析成功，且至少一个代表性功能真实跑通而非纸面检查
- 确认用的是协议原生工具（git 对 git 资源），未用手写 curl 绕过受保护抓取通道的安全边界

## Counterexamples
- 目标只是读一篇网页/文章并做分析摘要 → web_fetch 一次调用即停，整仓 clone 是错误工具且不必要
- 只需仓库中 1–2 个小文件 → 直接 raw 文件抓取比 clone 整仓更省
- 源不是 git 仓库（普通网站、归档页、纯 API 端点）→ 无 clone 可用，应走 web_fetch/归档恢复路径
- 环境策略明确禁止 git 网络访问时 → 不以 clone 名义绕行，按受限抓取路径或询问用户
