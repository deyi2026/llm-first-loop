---
method_id: locate-generic-named-task-script-by-artifact-domain-token-7a839dceabb9
name: locate-generic-named-task-script-by-artifact-domain-token
description: 任务点名一个通用文件名（gen.py/main.py 等）而工作区含 .venv/site-packages 等依赖树时，纯文件名检索会被依赖噪声淹没并诱发多轮宽枚举（本集先搜 gen 命中 20 条 venv 噪声，再宽搜又是无关脚本，第三次才靠内容词定位）。应直接用任务陈述中与目标工件绑定的领域专有词（如工件主题名）做文件名+内容联合检索，一次唯一定位；首次回执被依赖路径占多数本身即是切换判据。定位后 ls 同目录枚举基线工件与时间戳，再全文读取。
status: candidate
source_model: workbuddy/step-5-preview
source_episode_refs: episode:03b3d240-107f-45b2-af93-fd99abb8f1df:480:2e5ec3f06e52da36ce23
evidence_refs: learning:learn:abcaa5af55f1
created_at: 2026-10-17T19:39:05.497325+08:00
updated_at: 2026-10-17T19:39:05.497325+08:00
---
## Trigger
任务文本引用某脚本/文件但只给出通用名（gen.py、run.sh、config 之类），且会话中已出现与该文件绑定的工件主题词；或首次按通用名检索的回执命中大多来自 site-packages/.venv/.runs 等与任务无关的依赖路径。

## Discriminator
两条当时已知、无需未来信息的事实：(1) 任务陈述本身携带与被引用文件因果绑定的工件专有 token（本次为 pelican 骑车动画/15:43 基线），该词在依赖树中不存在，天然唯一；(2) 首次通用名检索回执显示命中被 cryptography/pydantic 等依赖文件占据，证明该文件名不具判别力，继续换措辞搜文件名只会重复同样噪声。

## Short path
- 从任务陈述提取与被引用文件绑定的工件专有词（领域名词），而不是把文件名当检索键
- 用 内容=专有词（可叠加 文件名=gen.py）做一次联合检索，预期唯一命中真实生成脚本路径
- ls 命中文件所在目录：确认任务锚定的基线工件（原版 svg/preview）及其时间戳与用户陈述吻合
- 全文读取脚本，进入参数化修改；后续数字全部以工具回执核准

## Stop conditions
- 定位到的脚本内容明确引用任务工件（docstring/输出文件名与主题一致）且其输出即基线工件 → 停止定位，进入读取与修改
- 专有词联合检索仍多义（同主题多项目并存）→ 停止继续换词枚举，改用输出目录约定或 mtime 对齐任务给定的基线时间来裁决

## Verification
- 命中脚本的 docstring/写盘目标与任务工件一致（如 gen.py 生成 pelican-bike.svg）
- 同目录存在任务锚定的基线版本文件，时间戳与用户陈述（15:43 原版）吻合
- 后续读取/执行回执的路径不再含依赖树（site-packages/.venv/.runs）

## Counterexamples
- 工作区没有 vendored 依赖树时，普通文件名检索一步即中，内容级联合检索纯属多余开销
- 任务本身就针对依赖库内部文件（真要改 site-packages 里的模块）时，按依赖路径排除会错过真目标
- 专有词在同系列多项目中重复（如多个 gen_images.py 服务同一专栏）时，内容检索仍多义，应改用目录约定/时间戳裁决而非继续换检索词
