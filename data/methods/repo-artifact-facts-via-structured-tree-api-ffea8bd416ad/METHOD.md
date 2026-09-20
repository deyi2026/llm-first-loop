---
method_id: repo-artifact-facts-via-structured-tree-api-ffea8bd416ad
name: repo-artifact-facts-via-structured-tree-api
description: 当用户问的是某个已明确仓库内特定变体/文件的存在性、大小、是否放得下等 artifact 级事实时，跳过开放式网页搜索，直接查该仓库的结构化清单 API（如 HF /api/models/{repo}/tree/main?recursive=true）：一次清单调用同时解决存在性+体积+预算适配；搜索引擎索引不到仓库文件树，只会返回营销/教程噪音。相邻变体清单仅在需要解释体积反常时才拉取；README 仅用于定性（质量/速度）子问题。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:09287651-af38-474b-954c-d2e1e665fb8e:24:33852bbc39f09b4d936d
evidence_refs: learning:learn:4809d59ac0fc
created_at: 2026-09-20T13:48:24.175877+00:00
updated_at: 2026-09-20T13:48:24.175877+00:00
---
## Trigger
用户询问一个对话中已确定的仓库里某个具名变体/文件的存在性、体积或是否适配已知数值预算（磁盘/内存），未知量是仓库树级事实而非概念性问题

## Discriminator
未知量是 artifact 级（该变体存在吗？多少字节？）且仓库 ID 已在上下文中——这类事实只存在于仓库的结构化 manifest（tree API）里，搜索引擎不索引文件树；同时任何硬预算已是已知数字，因此单一清单响应即可同时判定 exists+size+fit

## Short path
- 从对话上下文提取仓库 ID 与数值预算；未知量：所问变体是否存在、总大小多少
- 调用仓库结构化 tree API（尽量 recursive=true）→ 一次拿到全部变体目录与文件大小
- 将用户口语化变体名匹配到 manifest 条目（允许前缀/重命名差异，如 IQ3-XXS→UD-IQ3_XXS），对分片求和，与预算比较 → 存在性/体积/适配一次判定
- 仅当出现体积反常需要解释（如低 bit 反而更大）时，再从同一 manifest 拉 1–2 个相邻变体目录确认不变分量（如不随量化压缩的查找表分片）
- 仅当还剩定性子问题（质量/速度）时才读 README/model card；用户决策事实已对照 manifest 验证后停止

## Stop conditions
- 目标变体的存在性与总大小已从仓库 manifest 验证，且相对已知预算的 fit/no-fit 已判定
- 变体在 manifest 中不存在 → 直接报告不存在；此时才扩大到作者 org 页或官方文档，而非通用网页搜索

## Verification
- 总大小等于 manifest 中各分片条目 size 之和；变体名与 manifest 路径精确对应
- 适配结论由 manifest 字节数与用户陈述预算重新计算得出，而非来自搜索摘要或记忆中的数字
- 若引用了相邻变体数据，确认来自同一仓库同一时刻的 manifest，避免混入过期快照

## Counterexamples
- 问题是定性的（如『IQ3_XXS 在 Metal 上快不快/准不准』）——文件清单无法回答，应查 model card、官方文档或社区实测报告，此时搜索/抓取正文是正确工具
- 仓库身份尚未确定（如『有没有什么模型 80GB 装得下？』）——没有可列举的已知仓库，发现式搜索是合法的第一步
- 目标平台不提供结构化清单 API（论坛、纯文档站）——退回抓取权威页面，再考虑搜索
