---
method_id: paste-integrity-before-failure-diagnosis-16c60bbcaaf3
name: paste-integrity-before-failure-diagnosis
description: 用户以粘贴的终端输出作为失败报告时，先验证证据通道完整性：若出现重复提示符、traceback 在 token 中途截断并与命令文本拼接、缺少最终异常行、伴随 shell 级 parse error 等信号，则『新鲜执行失败』本身未被证实，枚举代码内部失败点是过早的。应先修复通道：回一条无续行符的单行命令获取一次忠实执行（可选一次性批量只读预检作对冲），拿到完整异常或成功输出后，才定位具体 raise 点。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:1712:74870b2229bb96861992
evidence_refs: learning:learn:ec652b543e72
created_at: 2026-09-19T07:25:43.649315+00:00
updated_at: 2026-09-19T07:25:43.649315+00:00
---
## Trigger
失败证据来自用户粘贴的终端文本，且粘贴呈现通道损坏信号：重复 shell 提示符、traceback 中途截断并与再次粘贴的命令文本融合、最终异常类型/消息缺失、或紧邻 shell 级错误（如 parse error near 换行/续行符）。

## Discriminator
第一条用户消息中已可见：zsh 报 parse error（shell 在执行前就拒绝了输入）、traceback 从未到达最终异常行、开头出现双重提示符。这只能证明至少一次粘贴尝试未真正执行、所示帧可能是旧滚回，因此不存在已证实的新鲜失败；待解决的未知量是『干净执行到底发生了什么』，而非『哪个内部校验失败』。

## Short path
- 把粘贴文本当证据审查：列出异常点（双提示符、token 中途截断、缺异常尾行、parse error），得出未知量=新鲜执行是否真的失败。
- 尝试复现前先核对权限围栏；若失败命令是 operator 专属或有副作用，真值来源是用户终端而非本机重跑。
- 回一条粘贴安全的单行命令（无反斜杠续行），使下次执行产生『一个提示符+一条命令+一个完整结局』；可把只读预检（状态文件、工作树、artifact 存在性）合并为一次调用作对冲。
- 干净结果返回后：成功→接后续流程；完整 traceback→只读末尾几帧并对应到源码中的具体 raise 点。
- 一旦拿到单次忠实执行的结果（成功输出或完整异常类型+消息）即停止枚举。

## Stop conditions
- 干净重跑产生完整结果：成功输出，或以明确异常类型+消息结尾的 traceback。
- 只读预检全绿且已交出单行命令——等待用户结果，不再继续枚举内部失败假设。

## Verification
- 返回的输出只有一个提示符、一条命令、一个完整结局，无交错或 parse error。
- 若失败，最终异常消息能对应源码中一条具体 raise 语句，证明诊断基于真实执行。
- 若成功，确认成功信号（如新 generation/状态落盘）后再定性原粘贴为通道损坏产物。

## Counterexamples
- 粘贴包含以明确异常消息结尾的完整 traceback 且其后有新鲜提示符——证据可信，直接诊断 raise 点，无需要求重跑。
- 命令非幂等或有破坏性副作用（发布/变更类操作）——不能贸然让用户重跑；改为只读核对前置条件并只索要旧输出缺失的尾行。
- 错误来自模型自己的实时工具调用而非用户粘贴——通道无损，走常规诊断。
- 终端已知支持 bracketed paste 或命令以脚本文件交付——多行粘贴安全，单行改写非必要。
