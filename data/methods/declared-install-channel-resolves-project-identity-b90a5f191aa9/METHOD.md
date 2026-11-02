---
method_id: declared-install-channel-resolves-project-identity-b90a5f191aa9
name: declared-install-channel-resolves-project-identity
description: 核实文章对具名软件项目的断言时，若正文自带精确安装标识（brew/pip/npm 包名），首探针用该分发渠道注册表而非搜索引擎：一条 brew info 类回执同时裁决存在性、版本、许可证并直接给出上游 canonical repo URL，把'项目是谁/在哪/能不能装'三个未知量压成一次查询；显示名含常见英文词（如 rapid）时通用网页搜索必退化为词典噪声。沿回执 URL 抓 README 比对数据表，再由平台元数据 API 补 stars/活跃度；核实全程保持只读（抓取写文件后解析，勿管道直进解释器）。
aliases: 怎么验证软件推荐文是不是编的, homebrew 元数据当项目百科用, 一条命令确认项目真实存在, 核对开源项目 star 数和更新时间, 文章吹的工具有没有官方仓库, 包管理器查官方仓库链接
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:3caec2da-e2d5-42be-80d2-60268ec4cecb:0:88be68c3dfb84c107140
evidence_refs: learning:learn:e6725e0cb354
created_at: 2026-11-01T19:26:31.874965+08:00
updated_at: 2026-11-01T19:26:31.874965+08:00
---
## Trigger
核实转述/测评类文章中关于某具名软件项目的可核断言（项目存在、stars、许可证、可安装性、引用基准数据）时，文章正文已逐字给出该项目的安装标识（如 brew/pip/npm install <包名> 或确切包名）

## Discriminator
断言自带分发渠道句柄：确切包名+安装命令已在手，对应注册表一条回执即可同时裁决存在性、版本、许可证与上游 canonical repo URL；且项目显示名若含常见英文词（如 rapid），通用网页搜索注定退化为词典/无关商业站噪声——首探针应选注册表而非搜索引擎

## Short path
- 从文章提取逐字包名/安装命令；未知量=项目是否真实存在、canonical 仓库在哪
- 查对应注册表（brew info <pkg> / pip index / npm view）：一次回执同时得存在性、版本、license、上游 repo URL；未知量收敛为'文章引用数据是否忠实'
- 沿回执中的上游 URL 抓 README，逐格比对文章引用的基准表/引语；命中则文章为忠实转述，剩余问题转为语义分析
- 文章若声称 stars/活跃度，用平台元数据 API（api.github.com/repos/<owner>/<repo>，curl 写文件后解析，不管道进解释器）一次拿 stars/pushed_at/release
- 注册表 miss → 转平台原生搜索按描述精确匹配候选；仍无则该断言记为存疑并报告，不换措辞重搜
- 每条可核断言各有一条权威回执后停止；顺带比对各渠道版本差异（formula 版本 vs README 基准版本 vs release tag）作为附加可信度信号

## Stop conditions
- 存在性/可安装性/数据一致性/stars 各有一条权威回执支撑
- 剩余差异均为语义判断（标题 vs 正文口径、厂商自测方法学），无新增可核未知量
- 注册表与平台搜索均无描述匹配候选 → 该断言判为不成立，冻结该分支

## Verification
- formula 回执的 homepage 与实际抓取的 repo 一致（排除镜像/同名干扰）
- README 数据表逐格等于文章引用值；API stars 与文章声称值取整后一致
- 本机环境探针（arch/内存）仅用于推荐适配判断，不复核上游事实

## Counterexamples
- 文章只给项目显示名、无任何安装标识 → 无注册表句柄，平台原生搜索/网页搜索才是正确首探针
- 任务是发现/比较同类项目（discovery）而非核实具名断言 → 宽搜索是目的本身
- 注册表命中的是同名抢注或无关 homonym（npm 常见）→ 命中≠身份成立，须用描述与上游 URL 反向对齐文章语境
- 用户只要文章摘要、未要求可信度核查 → 零探针直接总结即可
