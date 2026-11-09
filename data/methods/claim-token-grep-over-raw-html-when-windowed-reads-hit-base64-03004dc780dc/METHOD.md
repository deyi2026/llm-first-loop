---
method_id: claim-token-grep-over-raw-html-when-windowed-reads-hit-base64-03004dc780dc
name: claim-token-grep-over-raw-html-when-windowed-reads-hit-base64
description: 核验二手稿数字时抓一手网页，若首个回执/证据窗口被 @font-face 的 data:font/woff2;base64 内嵌资产占据（extract 退化、complete=false），不要按 4000 字窗口线性翻页找正文。改为把原始 HTML curl 落盘，用二手稿里已列出的待核数字/术语做定点 grep，由命中行上下文直接裁决每条 claim。窗口翻页在此场景下大概率连续命中二进制资产，而待核 token 清单本身就是现成的检索索引。
aliases: 网页抓回来全是字体base64怎么找正文, 分段读证据全是base64别一页页翻, 核数字直接在原始HTML里grep关键词, trafilatura提取出@font-face乱码, 二手稿数字核对一手来源定位正文, 证据水合窗口扫到一堆乱码怎么办
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:76c8948c-3ef1-455a-bb83-f699984dce07:0:085ef50cbc7d0c95487e
evidence_refs: learning:learn:0c0f4386b820
created_at: 2026-11-08T18:39:01.475722+08:00
updated_at: 2026-11-08T18:39:01.475722+08:00
---
## Trigger
需要对已取回二手文稿中的具体数字/术语做一手核验，而一手网页的抓取回执或首个证据窗口被内嵌 base64 字体/图片（如 data:font/woff2;base64）占满，工具只提供分窗口范围读取

## Discriminator
首窗口内容以 @font-face + data URI base64 开头且 complete=false，说明正文占比极低、顺序翻窗口会大量命中二进制资产；同时待核 token 清单（百分比、层号、参数量、模型名）在抓二手稿时已全部在手。这两点在开始翻页前就已可见，足以把下一步从『继续读下一个窗口』缩成『落盘+定点 grep』。

## Short path
- 从二手稿正文列出待核 token 清单：具体百分比、步数、层数、参数量、模型名等字面量
- 抓一手源；若首回执/首窗口即 @font-face base64，判定 extract 已退化为原始 HTML+内嵌资产，停止窗口线性扫描
- curl 原始页面落盘，脚本剥除 base64/CSS 或直接用待核 token 做 grep（词根+宽松正则）
- 由 grep 命中行上下文逐条裁决：命中=可验证；写法变形=放宽正则再试；零命中=标记为无来源细节
- 每条 claim 都取得原文行级对应或被证伪后停止

## Stop conditions
- 所有待核 token 均在原始 HTML 中找到行级上下文，或被确认零命中（记为无来源）
- grep 零命中且 HTML 为 JS 壳时，切换到接口/内嵌 JSON 数据层，不再继续翻窗口

## Verification
- 关键数字（如准确率区间）在原文有字面或数值等价出现
- 二手稿 claim 与 grep 命中行逐条比对，每处失真能指出原文对应位置

## Counterexamples
- 首窗口就是正常正文散文（无内嵌 base64）——直接窗口读取即可，落盘+grep 是多余一步
- 任务是通读全文而非核对特定 claim——不存在 token 索引，应换提取器或渲染后取文本
- 正文由 JS 从远程接口拉取、HTML 只是壳——落盘 grep 同样找不到，需改抓网络数据
