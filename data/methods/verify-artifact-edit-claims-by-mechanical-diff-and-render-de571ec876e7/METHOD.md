---
method_id: verify-artifact-edit-claims-by-mechanical-diff-and-render-de571ec876e7
name: verify-artifact-edit-claims-by-mechanical-diff-and-render
description: 用户要求'真的改/真的验证'或此前对大体积生成 artifact（SVG/产物文件）报过未核验改动时：任何关于内容的正/负向声称（已有X/没有X/坐标/尺寸）必须先由 artifact 机械检索（按元素 id/属性的 byte-offset grep）导出，不从记忆报数；编辑是否生效用改前 hash/snapshot + size delta + 渲染像素 diff 三重机械证据裁决，且 changed-pixel bbox 须与意图编辑区域重合。工具回执与 ls/stat 矛盾（如对 152KB 文件报'空文件'）时视为退化输出，以 shell 统计替代。
status: candidate
source_model: minimax/MiniMax-M3
source_episode_refs: episode:ae5b131c-d837-4549-8a3b-9f8d7168745d:123:cedeb8806cf261a6f184
evidence_refs: learning:learn:5acd3ca2d8ae
created_at: 2026-10-17T17:28:11.210776+08:00
updated_at: 2026-10-17T17:28:11.210776+08:00
---
## Trigger
用户用'真的/实际'强调核验（如'现在真的改并真的渲染验证'），或即将报告对大体积生成产物的改动清单，而清单中存在未经当前文件核验的历史声称（此前报过的坐标、尺寸、新增元素）

## Discriminator
磁盘 artifact 的机械事实（字节数、行数、元素 id 的 byte offset、tag 计数）与改动前 hash/snapshot_ref 是唯一 ground truth；记忆中的坐标/尺寸不构成证据。工具回执若与 ls/stat 矛盾（大文件返回'空文件'），该回执为退化输出，以 shell 字节统计为准

## Short path
- 冻结 baseline：记录 artifact 改动前 sha256、字节数、snapshot_ref
- 对每条将要声称的'已有X/没有X/坐标是a,b'，用 grep 按元素 id 或属性在文件内定位 byte offset；负向声称（'没有X'）必须全文件搜索无命中才可说出
- 执行最小编辑，读回新 hash、size delta 与 edit 链 snapshot_ref
- 用已存在的渲染脚本在代表性时间点渲染改前/改后帧，做像素级 diff
- 核对 changed-pixel bbox 是否落在意图编辑坐标附近；重合才声称改动生效，不重合先定位原因
- 如实撤回被证伪的历史声称（含被 grep 命中的'没有X'），停止追加新改动并交还决策

## Stop conditions
- 每条正向声称有 byte/hash 证据、每条负向声称有全文件 grep 无命中、编辑有 diff bbox 与意图位置重合的渲染证据
- 用户所需的'确实改了且确实验证过'已由三重机械证据支撑，不再继续新增改动

## Verification
- size delta 非零且方向正确（如 +201B 对应新增一段握把元素）
- 像素 diff 的 changed-pixel bbox 中心与意图编辑坐标重合，未编辑区域 diff≈0
- 改前后 hash/snapshot_ref 链路完整（edit 前后引用可追溯）
- 退化回执（read_file 报空但 stat 非零）未进入证据链

## Counterexamples
- 小文本文件一次 read 即可见全文：直接 read+diff 即可，渲染像素 diff 属过度流程
- 不可渲染的逻辑产物（配置/代码）：用 lint/测试替代像素 diff，但 hash 与负向声称的全文件核验仍适用
- 产物由生成脚本（如 gen.py）可再生：必须改生成器源码；手改产物即使 diff 验证通过，也会被下次生成覆盖
- 用户只要快速主观预览、不要求逐项核验时，逐条 byte-offset 定位可能是过度流程
