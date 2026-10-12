---
method_id: anchor-workdir-params-to-current-session-receipt-paths-91256589a15c
name: anchor-workdir-params-to-current-session-receipt-paths
description: 会话中文件读取回执已显示绝对路径后，再发 git/find/ls 等带根目录参数的命令时，workdir 必须取自本会话已验证回执的路径前缀，而不是从其他会话/环境的记忆路径取值。'workdir 不是有效目录'类回执是确定性参数错误而非暂时失败：从回执 provenance 或一次 pwd/git rev-parse 修正后重发，不重试旧根、不展开宽枚举。本集回执已多 zeigen 次显示 mirror 工作区绝对路径，命令却用了记忆中的旧根，造成全程唯一一次工具失败并多花一轮重定位根目录。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0e1e3567-343d-44ae-b119-9a2d6a9ee4c5:186:ca4c7d974c7a6834c114
evidence_refs: learning:learn:79e2b5e3d5fe
created_at: 2026-10-13T03:28:00.762478+08:00
updated_at: 2026-10-13T03:28:00.762478+08:00
---
## Trigger
准备发出带 workdir/根目录参数的命令（git、find、ls、脚本），且本会话此前已有携带绝对路径的成功工具回执

## Discriminator
本会话成功回执中已显示的绝对路径前缀（如 read_file 的 source/label 路径）即当前已验证根；待用根与该前缀不一致 ⇒ 该根是记忆先验而非当前证据，未经验证

## Short path
- 从最近一条成功回执的绝对路径提取当前已验证工作区根
- 直接以该根作为 workdir 发命令；根确有歧义（多个候选）时先一次性 pwd/git rev-parse 再发
- 收到'不是有效目录'类确定性参数错误回执时，从会话回执路径或一次 pwd/git rev-parse 修正根后重发一次，不重试旧根
- 回执成功且路径与会话已验证根一致即停止，继续原任务推进

## Stop conditions
- 命令回执成功，且返回路径前缀与本会话已验证根一致

## Verification
- 新回执中的路径前缀等于此前成功回执显示的根（或 git rev-parse 输出与之一致）
- 同一根不再复现参数错误回执；未因定位根目录而新增宽枚举或多余探查轮

## Counterexamples
- 任务显式指向与会话回执不同的另一个根/环境（如要求检查旧路径下的部署副本）——此时路径差异本身是目标，应显式验证该根而非强套会话前缀
- 会话尚无任何携带路径的成功回执——判别事实不存在，须先 pwd/git rev-parse 发现根，再作用域命令
- 会话中途工作区确实迁移且较新回执已确认新根——锚点应更新为最新回执的根，而非沿用最早回执或记忆值
