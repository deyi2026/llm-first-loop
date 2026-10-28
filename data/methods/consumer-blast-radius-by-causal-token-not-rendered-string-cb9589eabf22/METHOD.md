---
method_id: consumer-blast-radius-by-causal-token-not-rendered-string-cb9589eabf22
name: consumer-blast-radius-by-causal-token-not-rendered-string
description: 改 wrapper/gate 脚本的人类可读结论行而不动退出码前，影响面检索用因果 token（脚本调用命令、契约开关、机器可读状态标记）做作用域受限检索，不要拿渲染输出字符串做全库 grep：渲染串被发布快照与历史回执逐字复制，命中稀释且易超时。语义边界优先读被调工具自身契约就地确认（如 --require-complete 帮助文本已把发布资格与开发门禁分路），剩余未知量通常只剩『哪些测试断言显示行』，一次按调用命令的窄检索即可闭环。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7c026852-7867-4a41-9ab0-1340271874dc:640:ed564ed3dd619b81c3af
evidence_refs: learning:learn:3ff8265f5012
created_at: 2026-10-22T13:40:40.171505+08:00
updated_at: 2026-10-22T13:40:40.171505+08:00
---
## Trigger
准备修改某脚本/工具的人类可读输出（结论行/摘要行）且需先确认消费者与影响面，尤其当退出码与拦截语义保持不变、只有显示层变化时

## Discriminator
动手前已读到的被调工具源码就地给出契约分界：资格开关 --require-complete 的帮助文本明确『advisory 放行仅限开发侧 push 门禁，发布资格必须带此开关』，且工具打印机器可读状态标记（status=unknown）——消费者据此已可分为退出码/资格路径与显示行路径两类，无需全库扫描渲染串；而渲染串在冻结快照中的逐字副本（宽检索 40 命中几乎全是 .releases/ 与 docs 回执、两次 60s 超时）证明显示串不是判别键

## Short path
- 读 wrapper 脚本定位显示行与其调用的工具命令；未知量：改哪几行、显示与退出码是否同一路径
- 读被调工具源码的 advisory/完成分支与 argparse 帮助；未知量：契约开关把哪些消费者分到资格路径、机器可读标记是什么
- 用调用命令 token（如 bash scripts/ci_gate.sh）做限 tests//CI 配置的窄检索；未知量：是否有活跃测试断言显示行或退出码
- 实施修改：捕获子命令输出+退出码，非零照旧阻断，按机器可读标记二分结论行
- 新增双分支测试并对 HEAD 旧版做红对照（证明测试非空测），跑全量门禁后提交

## Stop conditions
- 契约开关已证明资格路径不消费显示行，且调用命令窄检索只命中已知测试/CI 文件 → 影响面闭环，停止枚举镜像与历史回执
- 宽检索回执为超时或命中被 .releases//docs 稀释 → 立即换因果 token 窄检索，不再用同一显示串重复宽搜

## Verification
- 新测试同时锁 unknown/complete 两分支输出；红对照：回滚 HEAD 版脚本后 unknown 用例必须 FAIL，证明测试非空测
- 退出码语义回归：advisory 仍 exit 0，资格开关路径未被改动
- 如实报告端到端盲区：unknown 分支仅被单测+红对照锁定，未在真实墙钟超时中复现

## Counterexamples
- 任务目标就是审计『渲染行被哪些文档/回执引用』（receipt 核验、文档声明比对）——显示串即检索目标，只需排除冻结镜像目录
- 库外系统逐字消费该输出（外部 CI/面板）——任何库内检索都覆盖不到，须沿脚本内已点名的外部 workflow/配置逐一核对
- 被调工具没有机器可读状态标记——无法按标记二分结论行，先给工具补标记属另一个任务
- 仓库无快照镜像且字符串唯一——全库 grep 便宜无稀释，窄 token 无增益
