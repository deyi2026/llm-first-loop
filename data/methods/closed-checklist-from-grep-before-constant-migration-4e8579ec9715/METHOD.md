---
method_id: closed-checklist-from-grep-before-constant-migration-4e8579ec9715
name: closed-checklist-from-grep-before-constant-migration
description: 当修改一个被多处引用、且被测试断言钉住数值的默认常量时，编辑前已获得的完整 grep 命中列表本身就是闭环修改清单：每条命中要么同步修改、要么显式排除（import 常量者无需改）；同时提交门禁必须读测试命令自身的退出码，不能用管道尾段(tail/head)的退出码替代。本例帧上限 64MiB→128MiB：grep 已列出 live_perception 测试两处钉旧值断言，却被“三处硬编码”的有损摘要漏掉，导致红测提交+补丁循环。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:2448:d61d45a1047ca0aaae93
evidence_refs: learning:learn:ed6aaa683a35
created_at: 2026-09-18T09:19:43.639117+00:00
updated_at: 2026-09-18T09:19:43.639117+00:00
---
## Trigger
需要修改一个具名默认值（常量+config 字段+env 默认三处硬编码），且旧字面量在 src 与 tests 中存在多处 grep 命中，其中部分测试断言直接钉住旧数值

## Discriminator
编辑动作发生前，grep 旧字面量（含 67108864 与 67_108_864 两种写法）的输出已逐行列出全部命中文件:行号，包括 test_smc_browser_live_perception_v01.py:227/286 中 max_frame_bytes=67_108_864 的钉值断言——该列表当时已把“需同步修改的文件集合”缩成闭集，无需事后靠红测发现遗漏

## Short path
- 由错误 diag 定位真正超限的请求：DOMSnapshot 47MB 帧本身可收（diag 实证 resp_chars/elapsed），失败在紧随其后的下一请求，错误模式 timeout→frame_too_large 已迁移
- 顺 capture 调用链读源码，确认 DOMSnapshot.captureSnapshot 之后紧邻 Accessibility.getFullAXTree，共用同一 max_frame_bytes 上限，默认 64MiB 在 2026 年大页尺度下误设
- grep 旧字面量两种写法覆盖 src+tests，把输出当作闭环编辑清单：逐条标注 改/引用常量不改/语义无关排除
- 一次性完成全部编辑，特别是直接钉数值的测试断言（frame_limit:141 与 live_perception:227/286 同批更新到 134_217_728）
- 提交前以 pytest 真实退出码为门禁（不接 tail/head 管道或启用 pipefail），全绿后单次 commit

## Stop conditions
- 同一 grep 重跑后旧字面量仅剩有意保留项（历史注释、无关子系统、import 引用处）
- 常量、config 字段、env 默认、全部钉值断言四处数值一致
- 单测套件以真实退出码全绿，或失败经基线对比证明与本改动无关

## Verification
- 改动后重跑同一字面量 grep，逐条核对无未对账命中
- commit 前单独读取 pytest 自身退出码，确认与 FAILED 行状态一致，不被管道尾段吞掉
- 若出现红测：先复跑定位钉值断言并补提交，而非让带 FAILED 的命令链顺带完成 commit

## Counterexamples
- 测试通过 import 常量断言（如 frame_limit L25/L73 引用 DEFAULT_CDP_MAX_FRAME_BYTES）而非字面量——这类命中无需也不应修改，盲改每行是错的
- 相同数字在无关子系统巧合出现（另一用途的缓冲大小）——需语义判断归属，机械全替换会引入错误
- 单处定义、无测试钉值的常量——直接改+局部验证即可，整套清单流程是过度开销
- 红测为基线上既有失败——应先跑基线区分归因，而非阻塞提交或误判为本次遗漏
