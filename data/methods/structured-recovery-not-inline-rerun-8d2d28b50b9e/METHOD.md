---
method_id: structured-recovery-not-inline-rerun-8d2d28b50b9e
name: structured-recovery-not-inline-rerun
description: 长耗时验证运行（全量测试/构建等）的结果已经过一次不可靠通道丢失后，重跑必须换成结构化、自解析的落盘输出（junitxml/JSON 等），而不是把同样脆弱的人类可读终端输出重定向到文件；且对已落盘 artifact 的内容疑问只用读取（tail/grep）回答，绝不把内联重执行生产者捆绑进同一条命令。本 episode 用 4 次全量运行 + 1 次超时才拿到一组数字，该方法可缩到 1~2 次。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T16:54:54.549050+00:00
updated_at: 2026-09-09T16:54:54.549050+00:00
---
name: structured-recovery-not-inline-rerun
status: candidate
trigger:
  - 需要从长耗时验证运行取得权威数值结果（计数/状态），而先前一次运行已通过不可靠通道丢失输出（进程回收只剩 exit 码、截断、摘要行被抑制）
  - 磁盘上已存在一份完整落盘的运行日志，当前问题是"它里面是否已含所需信息"
discriminator:
  - 交付物是机器可核对的计数/状态，不是人类叙述——这决定输出应选结构化格式
  - 生产者已成功完成过（exit=0 可见）：重执行不产生新信息，只有输出格式能改变信息可得性
  - 现有日志文件就在磁盘上："有没有摘要行"可用 grep/tail 在秒级回答，与重跑无关
short_path:
  - 任何重跑前，先 tail/grep 现有落盘 artifact，确认是否已含答案
  - 确需重跑：一次到位——结构化 reporter（如 pytest --junitxml）+ exit 码写入持久文件 + 后台运行（长命令永远不内联）
  - 完成后解析结构化 artifact 得权威计数；与预期口径有偏差时，从同一 artifact 提取分类明细（如 skip 原因分布）
  - 不顺带调查"为什么人类可读摘要缺失"这类支线谜题，除非它影响数字权威性
branch_on_evidence:
  - observation: 现有日志已含所需计数
    next: 直接报告并停止
  - observation: 日志完整但被 hook/配置抑制了摘要行
    next: 换结构化 reporter 重跑一次即可，不深挖抑制机制
  - observation: 工具根本没有结构化输出模式
    next: 全量 stdout 落盘已是正确机制，只需文件重定向，无需换格式
stop_conditions:
  - 从结构化 artifact 取得与 exit 码自洽的权威计数（exit=0 ⇒ failures=errors=0）
  - 或现有落盘日志已直接给出答案
verification:
  - 解析出的 tests/failures/errors/skipped 总和与退出码互洽
  - 计数与预期口径的偏差能用同一 artifact 的明细（skip message 分布）解释
anti_patterns:
  - 把"grep 现有文件"与"内联重跑全量生产者"捆绑进同一条命令——超时即全废
  - 生产者已 exit=0 后，再用与上次相同的输出格式重跑来"抢救"数字
  - 为拿一个数字反复重执行长任务，却从不改变输出机制
counterexamples:
  - 秒级冒烟测试：内联直跑即可，后台+结构化+解析属过度工程
  - 先前输出完整且含摘要行：直接读取，任何重跑都不需要
  - 问题需要失败详情（traceback/stderr 全文）而非计数：仅结构化计数不够，必须保留详细日志
programizable:
  - 命令预检：预计耗时超过超时阈值的长命令强制 run_in_background
  - 静态拆分：对已存在文件的 grep/tail 永不与执行类命令合并在同一条调用里
model_owned:
  - 判断所需结果是否必须机器可核对、结构化输出是否覆盖所需信息、何时放弃支线调查
why_shorter: 把"重复执行生产者+抢救人类可读输出"换成"一次改格式的结构化捕获+直接解析"，消除重复全量运行与超时浪费。
