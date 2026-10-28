---
method_id: content-anchor-scan-then-request-locator-579a415b0406
name: content-anchor-scan-then-request-locator
description: 上一轮提到、但当前上下文无路径的目标文稿，只能靠稀有内容 token（专有事件名、独特短语）识别时：不要做文件名/关键词变体式全库枚举（会被 .releases、site-packages 等噪音淹没）；用一次带排除清单与超时保护的有界内容扫描裁决『目标是否在可访问范围』，阴性则单层扩展（近期修改文件→常用用户目录）并检索会话记录里的 provenance；两者皆空即停止搜索，向用户索取路径或原文片段，并确认回写方式与外部授权。把『噪音淹没/同工具换参重试/超时』视为切换仪器的信号，而非继续枚举。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:bb10f7a5-7006-4dd0-b800-13d0f9a35fdc:78:587d4dce324c48500121
evidence_refs: learning:learn:1b8b9543d3d7
created_at: 2026-10-18T17:10:48.136284+08:00
updated_at: 2026-10-18T17:10:48.136284+08:00
---
## Trigger
用户要求编辑/引用一个先前会话讨论过的文件（文章、报告等），但其路径未进入当前上下文；目标内容含可识别的稀有 token（专有名、独特短语），而文件名未知。

## Discriminator
目标由稀有内容 token 唯一识别、文件名未知 → 文件名枚举对『是否存在』无判别力；且 search 工具回执里已显现噪音结构（.releases/<hash>/ 重复副本、.venv/site-packages），证明同工具换关键词只会继续被淹。唯一权威判据是对最独特 token 的一次有界、排除噪音、未超时截断的内容扫描；上一轮 locator 只可能存在于用户或会话记录中。

## Short path
- 明确未知量：目标是否存在于可访问存储、locator 是什么；选定最稀有且必然共现的判别 token（专有事件名+独特短语）。
- 一次有界内容扫描：工作区目标文件类型 + 显式排除噪音目录（.releases/.venv/site-packages/evals fixtures），带超时保护，核对退出码确保未被截断。
- 命中→读文件验证全部 token 共现后进入实际任务；0 命中→单层扩展：近期修改文件 + Downloads/Desktop/Documents 等常用位置。
- 仍 0→检索会话 archive/records：上一轮是否留下路径、交付记录或文档引用。
- 全空→停止搜索，输出已核实阴性清单，向用户索取路径或目标段落原文，并确认直接改文件还是出 diff、是否需要外部文档授权。

## Stop conditions
- 最独特 token 的有界扫描（退出码 0、未超时、排除项明确）为 0 命中，且有界扩展与记录检索均无 locator → 停止发现，向用户索取 locator。
- 找到包含全部判别 token 的文件 → 停止定位，进入验证与执行。
- 扫描超时或输出被截断 → 该结果不可作为阴性证据，换有界方式重跑一次，不得据此下『不存在』结论。

## Verification
- 阴性结论前：确认扫描范围、排除清单、退出码与输出行数，排除超时截断与范围遗漏。
- 阳性命中：确认全部（而非单个）判别 token 在同一文件共现，且语义与用户上一轮描述一致。
- 向用户报告时列出已覆盖范围，使『不在可访问位置』的边界可审计。

## Counterexamples
- 路径已在当前上下文或用户直接给出 → 直接读文件，禁止再扫描。
- 判别 token 太常见（如 'hooks'、'README'）→ 内容扫描会被淹没，应改用更独特的 token 组合或文件名/修改时间线索。
- 目标可能是非文件形态（在线文档/网页/二进制导出）→ 本地文本扫描阴性只支持『不在可访问文件范围』，不支持『不存在』，结论措辞与后续询问要相应受限（方法仍适用）。
- 检索工具已按相关度过滤且语料干净（无 vendor/重复目录）→ 无需自建排除清单，直接用工具即可。
