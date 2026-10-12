---
method_id: inspect-existing-artifact-directly-before-generation-record-hunt-064baa5920e7
name: inspect-existing-artifact-directly-before-generation-record-hunt
description: 当未知量是“某既有产物是怎么生成的/用了什么排版或参数”，且该产物的一份具体实例已确认在本地可读时，把产物本身当作权威规格直接机械检查（docx=zip，styles/document.xml 含 w:eastAsia 等显式声明），而不是去会话 Evidence、系统目录里搜“当时的生成命令”。产物终态自描述其关键规格；生成命令的记录很可能根本不存在于任何可搜索库。本集拿到上一份 DOCX 后做了 1 次越权目录搜索 + 3 次 evidence 搜索全部空手，最后直接 grep 上一份 DOCX 的字体声明（宋体×1、黑体×23）一次性取得全部排版规格，并用同样的计数验证了新产物。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6f6aaff7-affa-4ddd-ba99-dd5932331bbc:49:050e4630803705794e0d
evidence_refs: learning:learn:d973ea6bf5da
created_at: 2026-09-29T13:12:39.594292+08:00
updated_at: 2026-09-29T13:12:39.594292+08:00
---
## Trigger
需要产出与某既有产物同规格的文件（同样式 DOCX 等），存在“上一份用什么排版/参数生成”的未知量，且第 1 步目录列举已确认该产物实例存在于本地文件系统。

## Discriminator
本地已存在一份可读的同类产物实例（本集：deliverables/ 下的上一份 .docx，第 1 步 ls 即已列出），且其格式信息可机械提取——.docx 是 zip，内部 XML 显式声明字体/样式。这个当时已知事实足以把“生成方式”从“搜全部会话记录/系统目录”缩成“读这一个文件”，pandoc 甚至可直接以它作 --reference-doc。

## Short path
- ls 交付目录：确认模板 MD 与上一份 DOCX 同时在，并确认 pandoc 可用、python-docx 缺失（工具选型据此定为 pandoc）
- 读模板 MD 全文，确认与本单交易同口径（两亿估值、受让方版）
- 直接机械检查上一份 DOCX（unzip 后 grep word/*.xml 的 w:eastAsia/w:sz），一次提取排版规格：宋体正文、黑体标题及计数
- 按确认数字（2亿×0.5%=100万）填充模板生成新 MD
- pandoc 转换（必要时以上一份 DOCX 为 reference-doc），机械比对新产物 styles eastAsia 计数与提取规格一致、关键条款字符串在场
- present_files 申报交付物并报告路径，停止

## Stop conditions
- 已从既有产物实例直接提取到所需全部规格（字体/字号/结构/参数）
- 新生成产物与提取规格机械比对一致（样式计数、关键字符串），交付物已申报并给出路径

## Verification
- 比对新 DOCX 与参照 DOCX 的 styles eastAsia 计数（宋体/黑体）完全一致（本集两侧均为 宋体×1、黑体×23）
- 解包新 DOCX 核对关键交易字符串在场：¥1,000,000.00、0.5%、贰亿元
- 交付路径存在、字节数合理（18341B），present_files 成功回执确认

## Counterexamples
- 产物不可机械检查（加密、损坏、无内嵌元数据的纯二进制）——此时查生成记录/provenance 才是对的
- 问题不是“长什么样”而是“为什么这样、谁配置的”：产物只显示终态，意图与历史仍需 evidence/日志
- 存在多个同类产物实例且无法确定用户指哪一份——需先用 provenance 消歧再提取规格
- 产物已知过期或损坏，规格以现行 config/规范文件为准——直接读规范而非旧产物
- 需要精确复刻工具链版本或构建 flags，而产物内不含该信息——查构建/环境记录
