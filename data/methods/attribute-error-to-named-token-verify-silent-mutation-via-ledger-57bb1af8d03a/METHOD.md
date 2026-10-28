---
method_id: attribute-error-to-named-token-verify-silent-mutation-via-ledger-57bb1af8d03a
name: attribute-error-to-named-token-verify-silent-mutation-via-ledger
description: 多行 shell 回执里唯一的异常是一行报错（如 zsh: command not found: #），而关键变更命令（git update-ref/commit 等成功时无输出）看不到结果时，先用报错自带的主语归因：报错命名的是 #、空行、回显等非关键 token，说明失败不在变更命令那一行；逐行独立执行下单行报错不阻断后续命令。据此不要假设整块失败、也不要重跑非幂等变更，改查该变更的追加式权威台账（reflog、目标 ref 现值、新提交 parent==CAS 旧值）确认已生效后再收口。
aliases: zsh 井号注释报错后面的命令还执行吗, 命令块末尾报错是不是整段失败, update-ref 没输出是不是没生效, 报错后先查引用日志再决定要不要重跑, 静默命令怎么确认已经跑过
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:490:a01141b4171a3fbe16df
evidence_refs: learning:learn:288bc9e3b3aa
created_at: 2026-10-27T18:15:59.291763+08:00
updated_at: 2026-10-27T18:15:59.291763+08:00
---
## Trigger
粘贴或执行的多行终端回执中，一个成功时静默的变更命令（update-ref、commit、服务重载等）缺少可见输出，而相邻处有一行非致命报错，无法直接判断关键变更是否已执行

## Discriminator
报错文本自带失败主语：command not found: # 命名的 token 是注释符而非变更命令本身；命令为逐行独立执行（无 set -e、无 && 链），单行失败不中断后续行；静默成功命令本就不产生输出，缺输出≠失败——三条事实在回执里当时即可读出，无需重执行探测

## Short path
- 读报错主语定位失败行：主语是非关键 token（注释/空行/回显）→ 关键变更行未被点名，初步判定已进入执行
- 核对命令间连接方式：独立换行执行→报错不阻断后续命令；set -e 或 && 链→后续可能未跑，需另行确认
- 查变更自身的追加式台账：目标 ref 现值==期望新值、reflog 有本会话时间戳的更新条目、新提交 parent==update-ref 的 CAS 旧值
- 台账确认即判定变更已生效，继续收口与簿记；仅当台账反驳（无条目/值不符）才在 CAS 保护下重执行

## Stop conditions
- reflog/目标 ref 已显示旧值→新值的本次转移，且新提交 parent 等于 update-ref 传入的旧值（fast-forward 成立）
- 报错主语即关键命令本身，或命令处于 set -e/链式连接，判定变更未执行，转入重试分支

## Verification
- rev-parse 目标 ref 等于期望新提交
- reflog 存在本次时间戳的 update 条目
- 新提交的 parent 等于 CAS 旧值参数
- 工作树 status 中已提交文件无残留改动，确认落库内容即被验证内容

## Counterexamples
- set -e 脚本或 cmd1 && cmd2 链中一行报错会中断后续命令，不能推断后续变更已执行
- 报错主语就是关键命令（command not found: git、permission denied 指向 update-ref）→ 变更确实未运行
- 变更没有追加式台账（普通文件写入、无 journal 的手工操作）→ reflog 类证据不存在，只能靠输出回执或事后状态检查
- 关键命令本会打印结果（非静默）而回执里没有其输出 → 更可能根本没执行到该行
