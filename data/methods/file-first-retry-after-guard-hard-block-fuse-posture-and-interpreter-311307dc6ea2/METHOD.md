---
method_id: file-first-retry-after-guard-hard-block-fuse-posture-and-interpreter-311307dc6ea2
name: file-first-retry-after-guard-hard-block-fuse-posture-and-interpreter
description: 受限执行环境里，heredoc/stdin 直灌解释器会触发安全硬闸（灾难级行为）必被拦，而阻断回执本身就给出合规姿势：先把完整载荷落盘到允许写目录、再执行该文件，并明示载荷内受保护动作仍须走受管通道。方法：多行/嵌套引号载荷从第一步就采用落盘姿势；重试时把『投递姿势』与『解释器选择』一次收敛，直接用仓库权威环境（.venv 或入口脚本指名的解释器），不用 shell 默认 python3；受保护子动作拆出交 review_admission。可省一次必被拦的直灌尝试和一次默认解释器版本试错。
aliases: heredoc 被安全闸拦了怎么重跑, 先写临时文件再执行脚本, 内联 python 载荷被硬阻断, 守卫回执里的等价姿势照抄, 管道喂解释器被阻止后换姿势
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a43dc767-17c2-429a-82f3-1dd9d4aa5558:197:e504e9b5905bd4ad27ae
evidence_refs: learning:learn:423b4e1ac54f
created_at: 2026-11-15T22:11:39.314878+08:00
updated_at: 2026-11-15T22:11:39.314878+08:00
---
## Trigger
在带安全硬闸的受限环境执行多行或含嵌套引号的解释器载荷（临时脚本、定向 pytest）；或一次行动已被守卫以灾难级硬阻断、且回执内嵌『可复制的等价姿势』

## Discriminator
阻断回执/常驻规则同时明确两点：①直灌解释器必被硬阻断，合规姿势=载荷先落盘再执行该文件；②落盘只解决投递层，载荷中的受保护动作（push、全量测试等）仍会被拦、须单独走 review_admission——这两句合起来就是重试命令形状的完整规格，无需自行发明绕法

## Short path
- 判定载荷形态：多行或含引号嵌套 → 从一开始就用落盘姿势，不做直灌尝试
- 把载荷完整写入允许写目录（工作区/缓存）下的文件；解释器一次选对：取仓库权威运行环境（.venv/bin/python 或被点名入口脚本所用解释器），不用 shell 默认 python3
- 执行该文件并解析输出；载荷中的受保护动作拆出交 review_admission，其余部分留在脚本内
- 执行后复核 git status --porcelain 与执行前一致（临时文件不得污染 tracked 区）

## Stop conditions
- 载荷以合规姿势执行完成、输出可解析、工作区状态不变
- 文件姿势二次被拦且回执指向受保护动作 → 停止本地继续变形载荷，转 review_admission/escalation

## Verification
- 全程无第二次同类硬阻断；无解释器版本级 ImportError（如 StrEnum 缺失类错误）
- 执行前后 git status --porcelain 完全一致

## Counterexamples
- 单行简单命令：直灌合法且更快，落盘是多余的间接层
- 无此类安全硬闸的环境：heredoc 直灌是标准做法，不应加间接层
- 载荷核心就是受保护动作（git push、全量测试）：落盘只解决投递层、绕不过动作层，必须走受管通道，不得继续改形载荷试图本地通过
