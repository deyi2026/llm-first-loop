---
method_id: github-actions-0s-parse-failure-annotation-before-local-lint-8ec2ede071ac
name: github-actions-0s-parse-failure-annotation-before-local-lint
description: CI 中某条 workflow 固定 0 秒失败且无任何 job 被调度（注册名回退成文件路径、失败页提示 workflow file issue）时，这是平台侧文件解析/注册失败而非任务失败：诊断首选该 run 的平台 annotation（file:line:col + 语法错误消息），因为平台的 DSL 校验面——如表达式记号校验，即使在注释里也执行——超出本地通用 YAML 解析器的可见范围。定位后只做最小改写避开记号序列；本地 lint 通过不能自证修复，远端生效以下次 push 的 run 为准。
aliases: GitHub Actions 秒挂没起 job, workflow file issue 怎么排查, actions 一推就红 0 秒失败, 注释里写表达式语法把 CI 写挂, An expression was expected 在哪定位, workflow 注册失败名字变成路径
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:4324:45f81515508ccab4c1cb
evidence_refs: learning:learn:1a24646e378c
created_at: 2026-10-30T19:40:59.034787+08:00
updated_at: 2026-10-30T19:40:59.034787+08:00
---
## Trigger
某条 GitHub Actions workflow 在连续多次运行中固定 0s 失败、job 列表为空（或注册名回退为文件路径），同一 push 的其他 workflow 正常执行；或失败详情页直接给出 workflow file issue 类横幅。

## Discriminator
失败时长 0s + 无 job + 平台横幅指认 workflow 文件问题 ⇒ 错误坐标只存在于平台 annotation（file:line:col 与诸如 An expression was expected 的语法消息）；本地 YAML lint / 重复键 / BOM 检查对平台的表达式记号校验（含注释内字面量 ${{ }} 空表达式）结构性失明——该签名在首次 CI 列表回执里即已可见，无需先通读文件。

## Short path
- 识别 0s / 无 job / 文件问题横幅 ⇒ 把第一未知量定为『平台解析器卡在文件哪一行』，排除 runner、环境、脚本级假设
- 直接拉取该 run 的 annotations（网络瞬断 EOF 只重试一次），取得精确 file:line:col 与错误消息
- 只读 annotation 指定位置的邻近片段，识别触发记号——典型：为规避插值而写的防御性注释/字符串里逐字引用了字面量 ${{ }}
- 最小改写避开记号序列（改措辞或拆开括号），不做无关重构，提交
- 本地仅验证通用 YAML 良构性；把『远端生效』显式标记为待下次 push 验证，不让本地通过充当修复结论

## Stop conditions
- annotation 指认的位置已最小修复并提交，且本地 YAML 解析通过（远端验证显式移交下次 push）
- 确认失败并非文件级解析：run 有时长、有 job 已执行 ⇒ 退出本方法，转普通 job 失败调试

## Verification
- 下次 push 后该 workflow 能调度出 job（时长 >0、出现 job 列表）即证明注册恢复
- 修复 diff 只含记号序列规避，无语义或结构改动；期间若存在同仓库其他全量扫描 job 仍绿，可注明兜底

## Counterexamples
- workflow 运行数分钟后失败（job 真实执行过）：是任务失败，annotation 可参考但记号排查无关
- 本地 YAML 解析器本身就报错：普通语法错误，本地修复即可，不需要平台 annotation
- 自建 runner 或其他 CI 平台的 DSL：注释内记号是否被校验取决于具体解析器，不能默认 GitHub 的校验语义
