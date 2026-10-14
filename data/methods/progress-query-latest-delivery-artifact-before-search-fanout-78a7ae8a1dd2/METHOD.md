---
method_id: progress-query-latest-delivery-artifact-before-search-fanout-78a7ae8a1dd2
name: progress-query-latest-delivery-artifact-before-search-fanout
description: 对『某能力/工作流进度如何』类状态询问：首个 search miss 回执若已点名 docs/ 为最近权威文档目录，且 status 回执显示当日部署活动，则进度真值就是该目录里最新的交付工件，一次 ls -lt 按时间排序即可命中；不要接着换 store 做 search_evidence/search_files 宽枚举。答案以『报告数字 + status 存活回执』为双源；仅当报告核验清单与回执之间存在唯一缺口（如 HTTP 冒烟）时用最小探针补齐（端点路径从报告/设计文档点名的端点直接 grep），而非全库端点考古。与 resume-continuation 方法不同：后者沿被点名的 provenance edge + git delta 重建续跑状态，本方法靠『命名约定+时间排序』在 miss 回执未直接命中答案时定位最新交付真值。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:89b60cd3-41c3-4e13-ba52-f4f3dcd83454:92:3e43b7b7eea029b4607a
evidence_refs: learning:learn:51f2613f3865
created_at: 2026-10-13T21:03:11.290655+08:00
updated_at: 2026-10-13T21:03:11.290655+08:00
---
## Trigger
用户询问某工作流的进度/交付状态（如『X 开发进度怎么样』），无活动 goal；首个 search miss 回执已点名 docs/ 等最近文档目录，或 status 回执显示当日 generation/commit/restart 部署活动。

## Discriminator
status 回执已证实当日 restart succeeded、web pid@最新 commit、matches_desired_generation=true；同时 search_docs miss 回执点名 docs/ 为『最近文档参考』目录（尽管其列出的参考未直接命中目标）。两点合计在当时即足以判定：进度真值在 docs/ 最近交付工件中，一次 ls -lt 即可命中 phaseN-delivery-report.md，无需再换 evidence/file store 枚举。

## Short path
- 读 status 回执：确认当日部署活动与存活状态（未知量：交付是否已上线）
- 沿回执点名的 docs/ 做 ls -lt 时间排序：命中最新 phaseN-delivery-report.md（未知量：进度真值在哪份工件）
- 读该报告：取得交付数字、机制、回归结果与 §核验清单（未知量：进度内容）
- 对照报告核验清单与 status 回执：已证实项不重做；仅剩缺口（如 HTTP 冒烟）用一次最小探针补齐，端点路径从报告/设计文档点名的端点字符串直接 grep 定位，不做全库渐进式内容考古
- 答案双源收口：交付数字溯源报告工件，存活断言溯源 status/探针回执，停止

## Stop conditions
- 最新交付报告已读且其部署声明与 status 回执一致（探针仅补唯一缺口）即停止，不进入全库端点考古或跨 store 换措辞重复搜索
- 若 docs/ 无匹配该工作流的交付报告（命名未命中且近期无相关 mtime），改走 git log / goal / evidence 真值源，不再继续同义搜索

## Verification
- 答案中每个交付指标可指回报告工件；每个『已上线/存活』断言可指回 status 回执或探针 HTTP 状态码
- 报告日期不早于最后已知 commit/部署事件（否则报告过时，需叠加 git delta 核对）

## Counterexamples
- 询问的是代码行为/实现细节而非交付进度：交付报告可能省略或过时，应直接读代码与测试（repo-api-discovery 场景）
- 目录 mtime 被批量操作 touch 失真且无 delivery-report 类命名约定：时间排序判别失效，退回搜索或 git log
- 报告落盘之后仍有新提交：报告不是当前态，进度需叠加 git delta（resume-continuation 场景）
- 进行中、尚无交付报告的工作流：最新工件不存在，只能查活动 goal/evidence/git log，ls 排序无从命中
