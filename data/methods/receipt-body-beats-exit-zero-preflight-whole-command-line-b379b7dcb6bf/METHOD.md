---
method_id: receipt-body-beats-exit-zero-preflight-whole-command-line-b379b7dcb6bf
name: receipt-body-beats-exit-zero-preflight-whole-command-line
description: 长时验证 job 的持久回执 exit=0 不等于验证已运行：命令被 | tail 类管道包裹时，command not found 等调用层错误会被尾段恒成功掩盖。判据是 runner 必有的摘要行是否在正文出现。发现调用层失败后，把整条命令行视为未经本环境验证（命令存在性+每个非标准 flag 与已装工具匹配），一次廉价预检后用最小已知可用命令重跑，而不是只删错误行点名的那一个 token 再跑。上轮状态账本里『进行中/已放行』的验证声明在回执正文核实前一律当作未发生。
aliases: exit 0 但测试没跑, 退出码被 tail 管道盖住, 测试空跑怎么发现, 重跑前整行校验命令, 回执没有摘要行就是没跑, command not found 但退出码是 0
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:853:705e616bde3dc6bfc6d1
evidence_refs: learning:learn:4170ca083657
created_at: 2026-10-30T07:29:34.289105+08:00
updated_at: 2026-10-30T07:29:34.289105+08:00
---
## Trigger
续跑或验收时读取长时验证（全量测试/构建/扫描）job 的持久终态回执：退出码为 0，但命令行被管道（| tail）包裹，或正文出现 shell 级错误文本、缺少该 runner 必有的终端摘要行

## Discriminator
合法运行的终态必有摘要行（pytest 的 N passed/failed、no tests ran 等）。正文出现『command not found』『unrecognized arguments』或完全没有摘要行，说明 runner 从未执行任何工作；exit=0 来自恒成功的管道尾段（tail），不是测试绿。

## Short path
- 读 job 回执全文而非只看 exit code，检查 runner 必有摘要行是否存在
- 无摘要行或正文含 shell 错误 → 判定『验证从未发生』；把依赖它的结论（门禁放行、完成度、上轮状态账本的进行中声明）全部降级为未验证
- 重跑前对整条命令行做一次廉价预检：命令存在性（command -v；macOS 无 timeout）、每个非标准 flag 与已装工具/插件匹配（pytest --help 或插件清单）
- 剥除预检不过的元素，用最小已知可用命令重跑一次；等到终态且正文出现摘要行才采信结果
- 出现真实失败时归因本轮产物；注意修复会改变产物指纹、使既有审查 PASS 失效，需窄复审后再放行

## Stop conditions
- 终态回执正文含 runner 摘要行，且结果与门禁/验收口径一致
- 预检确认命令行所有元素在本环境可用后，重跑一次即拿到含摘要行的终态

## Verification
- 最终引用的 job id 与含摘要行的回执一致，退出码与摘要行结论相互印证
- 命令行中每个元素（命令与 flag）都过了存在性/支持性检查，无一凭记忆或沿用旧命令行照搬

## Counterexamples
- 回执正文已有正常摘要行（如 9683 passed）→ exit=0 可信，无需预检或重跑
- 命令未被管道包裹、无 wrapper → 退出码直接可信
- 秒级幂等命令重跑成本低于预检 → 直接重跑更省
- 环境本身具备这些元素（Linux 有 timeout、已装 pytest-timeout）→ 原命令合法，本方法无话可说
