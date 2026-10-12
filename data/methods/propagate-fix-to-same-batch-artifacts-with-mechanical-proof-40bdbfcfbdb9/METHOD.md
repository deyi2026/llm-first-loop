---
method_id: propagate-fix-to-same-batch-artifacts-with-mechanical-proof-40bdbfcfbdb9
name: propagate-fix-to-same-batch-artifacts-with-mechanical-proof
description: 同一份内容在本任务中被拆成多个同源 artifact：正文 md、由相同引文/参数生成的图脚本与 PNG、转出的 HTML、各平台发布稿。本集三次同型事故：①fig34 底部越界(B=0)确诊并加高画布后，随后新写的 _d11.py 仍用旧画布，fig35/36 再次 B0；②改正文引文后未同步 fig33，图中保留了任何记录中都不存在的旧引语，被独立审稿抓为 P1；③尾注补丁断言失败被误读成成功，错误措辞上线两站，公网验收才发现，被迫 md/头条/知乎三方同修。规则：对任一 artifact 施加已确诊的修正（内容或参数）时，立即枚举同批同源兄弟 artifact，逐个施加同一修正，并用 grep 旧串零命中、图 margins B>0、断言 PASS+SHA 变更等机械证据证明每个都改到，之后才进入审稿/发布；『脚本跑了/退出码 0』不等于『改成了』。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:fe0e1465-7509-459e-8792-eaaf6d7269f5:530:6a4ab4b5db42b15e4207
evidence_refs: learning:learn:9811a4da126f
created_at: 2026-10-12T20:10:21.107645+08:00
updated_at: 2026-10-12T20:10:21.107645+08:00
---
## Trigger
对会话内某个 artifact 做了内容或参数修正，且同批存在从同一源文本/同一生成器派生的其他 artifact（图脚本与 PNG、转出 HTML、各平台发布稿）尚未同步复核时

## Discriminator
修正当时即可机械确认的同源证据：旧引文/旧措辞字符串能被 grep 到兄弟脚本或稿件中；上一 artifact 刚确诊的失败参数（如 B=0 裁切、断言 MISS）原样出现在新生成物回执里。命中任一即存在同批版本倾斜

## Short path
- 修正任一 artifact 后，列出同批同源清单：生成它的脚本与产物、同一引文/数值出现的其他文件、由它转出的 HTML 和平台稿
- 对每个兄弟 artifact 施加同一修正：改正文引文→同步改图脚本并重出图；确诊画布高度→同批新脚本直接采用已验证参数
- 逐个机械复核：grep 旧串零命中、图回执 margins B>0、补丁断言显式 PASS 且文件 SHA 变化
- 全部通过后才交审稿或发布；任一失败回到上一步，不得先发布后补修

## Stop conditions
- 同批所有 artifact 复核通过：旧串 grep 零命中、图无 B=0 越界、断言 PASS 且 SHA 已变更
- 确认某兄弟 artifact 与修正源无同源关系（内容/数据独立），明确豁免并记录理由

## Verification
- 对每个曾含旧内容的文件重跑 grep 旧字符串，期望零命中；不得以『命令退出码 0』或『脚本已运行』替代
- 补丁脚本必须内建断言并在输出中显式 PASS，同时打印新 SHA；图类 artifact 以生成回执的 margins 行为判据（B=0 视为未修复）

## Counterexamples
- 兄弟 artifact 数据或叙事彼此独立（如正文改动与图中实测数值无关）时不得盲同步，否则会把正确内容改错
- 各平台稿件有独立格式与字数约束（如知乎/头条尾注规范不同），同步时需按平台重写并各自复核，不能整段机械替换
- 首次出现的未知缺陷（如本集 fig34 首次 B0）应先诊断根因再修；本方法只约束『已确诊缺陷在同类产物上的重复发生』
- 单文件、无派生物的简单修改任务不适用
