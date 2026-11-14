---
method_id: named-origin-host-artifact-locate-by-output-convention-910368eec9c3
name: named-origin-host-artifact-locate-by-output-convention
description: 用户把目标制品明确归属到另一台主机上的 agent 实例（如『Deepin 的 lfl 写的文章，你来发表』）时，制品位置由来源主机+该实例自身的输出约定决定，本地发现面（repo 全文搜索、help 收件箱、workspace outputs 枚举）注定不含目标正文。先解析主机连接（ssh config / 既往 experience 记录常已含地址与目录布局），再在远端按 outputs/lfl-article-<当日日期>/ 式约定定位正文+证据台账+配图三件套，sha256 指纹与作者侧核对后取回；本地只做一次有界读取（当日 STATUS 总账）用于排期占位与防重发。省掉对本地库的多轮无效枚举。
aliases: 去另一台机器上取 lfl 写的稿, Deepin 上的文章怎么拿, 远端 agent 产物在哪找, 跨机取稿先连主机, 按日期找远端 outputs 目录
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:3ce44b7b-1df4-4d72-a3ae-9273fd084428:0:8c4e699e32e944c45acc
evidence_refs: learning:learn:b4e1cd28512b
created_at: 2026-11-13T16:18:21.641413+08:00
updated_at: 2026-11-13T16:18:21.641413+08:00
---
## Trigger
用户请求对一件已被明确归属到另一台主机/另一 agent 实例的制品（『X 机器上 lfl 写的文章』）执行动作（发表/审阅/同步），而本机同时存在多个易被误当作发现面的本地库（代码仓、workspace outputs、STATUS 台账、help 收件箱）

## Discriminator
请求措辞本身已给出制品的因果来源=远端主机；且开局排程/coordination 回执若只列出本地排期稿（当日各班次均另有其稿），即同时证明目标制品不可能出现在任何本地内容库——本地全文搜索、收件箱与 workspace 文章枚举注定空转

## Short path
- 从请求措辞锁定来源主机；第一未知量=怎么连：读 ssh config 与 records/experience 中该主机的既有条目（连接方式与目录布局常已在记录中）
- 第二未知量=远端产物在哪：在该实例的远端工作区按其输出约定定位当日目录（如 outputs/lfl-article-<日期>/），列出正文/证据台账/配图三件套
- 第三未知量=是否作者终版：取回时逐件核对 sha256 指纹与远端作者侧记录一致，避免拿到中间稿
- 本地只做一次有界上下文读取：当日 STATUS 总账确认排期占位与防重发（如提示晚班排班会话勿重复发表），不用于内容发现
- 沿既有发布闸门链（机检/独立审查/宿主准入）发布并公网回读核验；平台『审核中』时延如实上报并按承诺时间点复查，不自动重发

## Stop conditions
- 远端当日产物三件套指纹核对一致，即停止一切发现类搜索，进入呈现适配与闸门流程
- 远端约定路径下无当日产物时，只回到远端 workspace 根做一层列举重定位，不转回本地搜索
- 公网逐行核验命中后停止复查轮询，剩余动作仅剩按既定时间点复查平台状态与如实报告遗留项

## Verification
- 取回的正文/证据台账/配图 sha256 与远端作者侧记录完全一致
- 公网页关键串、图注、数字 token 与台账逐项命中
- 当日排期台账已标注本文占位，防重发提示已送达相关会话

## Counterexamples
- 制品已通过 peer 收件箱 / mirror receipts 等投递渠道到达本地时，先查投递渠道而非 SSH 远端——『归属远端』不等于『必须远端取』
- 措辞只描述作者身份、但产物确为本地排期稿（STATUS 已列出）时，本地精确路径读取即可，无需连远端
- 远端实例目录布局未与本机对齐（无共享输出约定）时，先读远端配置/记录确认布局，不能直接套本机路径约定
