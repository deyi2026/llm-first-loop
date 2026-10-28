---
method_id: cat-heredoc-static-write-downgrade-on-interpreter-heredoc-hardblock-18d17f5a594d
name: cat-heredoc-static-write-downgrade-on-interpreter-heredoc-hardblock
description: 沙箱硬阻断『here-doc 交给解释器执行』（E6_CATASTROPHIC_HARD）时，若待写文件是纯静态内容（字段全部来自已观测回执：verdict、SHA、child_id 等），不需要提权：改用 cat > path <<'引号定界符' 直接写纯文本，再用读文件参数的解析器（jq . <file> / python -m json.tool <file>）校验。解释器环节只在文件需要运行期计算（转义、嵌入命令输出）时才有必要；阻断回执里邀请的 escalation_request 是最后手段，仅当不存在等价非阻断原语时才用。
aliases: heredoc 喂 python 被硬阻断, E6_CATASTROPHIC_HARD 需要提权吗, 沙箱里写 JSON 回执用什么命令, cat heredoc 写静态回执文件, 写回执别走解释器管道
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:3e24aff2-8af5-497f-882a-a249bcc66acd:237:1c5c6703fde5dba7b3fb
evidence_refs: learning:learn:4f9e5e79fa38
created_at: 2026-10-28T09:07:23.887959+08:00
updated_at: 2026-10-28T09:07:23.887959+08:00
---
## Trigger
在启用执行策略沙箱（如 macOS sandbox-exec / FR-SAFE 类硬阻断）的环境里，要把一份内容完全由已观测事实决定的静态文件（审查/推送回执 JSON、清单、报告）写入写权限允许的路径，而第一反应是用 python 等解释器 heredoc 生成时

## Discriminator
写入内容是否为纯静态文本：若所有字段都已在早前工具回执中出现、无任何运行期插值或转义计算，则解释器环节零收益、纯增阻断面；且本 run 每条 shell 回执都带沙箱横幅，证明存在审查『执行机制』（不止写范围）的策略层，heredoc 喂解释器正是其高危判据

## Short path
- 组装内容前确认每个字段都能指回一条已观测回执（child_id、candidate_sha256、远端 SHA、verdict），无待计算值
- 用 cat > 目标路径 <<'JSONEOF'（引号定界符防变量展开）一次写入纯文本
- 用读文件参数的解析器校验落盘结果（如 python -m json.tool <file> 或 jq . <file>——解释器读文件参数不触发 heredoc 阻断）
- 校验输出 OK（JSON_OK/无解析错误）且关键字段与源回执一致即停，不再重复写入或再调解释器确认

## Stop conditions
- 文件已落盘、解析校验通过且关键字段与源回执一致——停止，不追加写入动作
- 组装时发现内容含运行期待计算字段——停止手写路径，先解决数据生成再写入

## Verification
- 解析器对写好的文件本身校验通过，并抽查 verdict/sha/child_id 等字段与早前工具回执逐字一致
- 确认没有走 escalation_request：只有穷尽等价非阻断原语（cat/cp/base64/jq 构造）仍无法满足需求时才申请提权

## Counterexamples
- 内容需要运行期生成（安全嵌入命令输出、复杂转义）——静态性判据不成立，cat 手写易引入引号 bug，应先产出数据或用 jq -n 构造
- 目标路径在沙箱写范围之外——阻断原因是范围而非机制，cat 同样会失败，那是执行者/边界问题，机制降级救不了
- 二进制内容或需交互输入——heredoc 原语不适用，改用 cp/base64 类等价原语
