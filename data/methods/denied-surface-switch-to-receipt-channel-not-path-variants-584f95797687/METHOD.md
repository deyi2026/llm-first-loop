---
method_id: denied-surface-switch-to-receipt-channel-not-path-variants-584f95797687
name: denied-surface-switch-to-receipt-channel-not-path-variants
description: 沙箱拒绝(exit 71 sandbox_apply)、参数错误明示隔离树根=父工作区HEAD、read_file登记路径不存在(TTL 24h)之后，仍用路径/工具变体反复探测同一表面(cd重试、/private/tmp变体、ls .git)是纯搜索空间扩散：本集4-5次确定性失败零新信息。正确做法：把所需事实逐项路由到已在产出它的权威回执通道——live版本身份读service_control的deployment字段(git_head/generation/matches_desired_generation)，被测树身份与质量用在目标树上执行的准入闸SHA一致性+PASS；无法由回执供给的事实(如porcelain清单)标注未核验并给来源标签。核心抽象：在目标表面上执行的闸门回执本身就是该表面状态的权威采样，本地直读对裁决非必需，故整体步数更少。
aliases: 沙箱报错git读不到怎么办, 文件不存在已登记还要再试吗, 读不了工作树用部署回执对版本, 准入PASS能不能当版本证据, 被拒后换路径重试还是换通道, 隔离环境看不到外部目录
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:26f09150-ab38-4082-81e9-9a0a7f5b8b6f:262:2a46e59468c29ae15de7
evidence_refs: learning:learn:6d89ff17569e
created_at: 2026-10-31T22:36:08.888597+08:00
updated_at: 2026-10-31T22:36:08.888597+08:00
---
## Trigger
环境级确定性拒绝回执（沙箱 apply 失败、隔离树语义参数错误、路径已登记不存在并显式建议停止搜索）之后，仍需要该不可达表面上的事实（外部工作树的 git HEAD/工作树状态、live 版本身份），且同时已有权威回执通道正在产出同族事实（部署状态回执的 git_head/generation/matches_desired_generation；在该目标树上执行的准入/审查闸回执的 candidate_sha256 与 verdict）。

## Discriminator
两个当时已知的事实：(1) 拒绝回执的语义类别是确定性环境语义而非 transient——exit 71 sandbox_apply、参数错误明文说明工具树根=父工作区当前HEAD（外部绝对路径不可寻址）、read_file 失败回执显式登记该路径不存在并建议停止该路径搜索；(2) 所需事实可由已有回执供给——service_control status 的 deployment 字段给出 live git_head 与 matches_desired_generation，admission start/status 的 SHA 绑定+PASS 直接证明被测树的身份与质量。任一事实在当时即可把『继续想办法直读 git』缩为『停止该表面探测，改走回执通道』。

## Short path
- 对目标表面做一次合法探测（如一次 git log/status 命令），获取未知量：直读是否可用
- 收到确定性环境拒绝（沙箱 apply 失败或隔离树语义错误）→ 判定该表面在本环境不可直达，不再做路径/工具变体重试（不换 cd 前缀、不换 /private 前缀、不 ls .git）
- 列出仍需的事实清单并逐项映射到供给通道：live 版本身份→部署状态回执；被测树身份与质量→准入闸回执；对端落定→闸门 start accepted + topology lease/事件回执
- 从 service_control 回执读 deployment.git_head/generation/matches_desired_generation 作为版本身份；从 admission start 记 SHA 基线，阻塞等待+status 轮询到终态
- 终态回执核对 SHA 与 start 基线一致后停止；无法由回执供给的事实（工作树 porcelain 直读）在最终报告中显式标注未核验及来源标签，不重试已拒绝表面
- 如该未核验事实是用户硬性验收项，向用户求证或请求换环境，而不是用替代回执宣称已核验

## Stop conditions
- 所需事实已由权威回执供给且交叉一致（admission status SHA == start SHA；service_control live git_head 与 desired generation 匹配）
- 某事实经确认无任何回执通道可供给 → 以『未核验』上报并给来源标签，停止一切对该表面的探测
- 拒绝回执被识别为状态变迁型（回执提示文件可能刚被创建）→ 仅在状态变迁事件后做一次重新 read，不进入变体枚举

## Verification
- admission start 与 status 回执的 candidate_sha256 逐字节一致，确认非旧回执或不同目标
- service_control 回执中 matches_desired_generation=true 且 git_head/generation 与报告引用一致
- 最终报告明确区分『回执来源事实』与『未能直读的事实』（如 git porcelain、取消失败的 schedule 各自标注）

## Counterexamples
- 拒绝是 transient（timeout、偶发权限抖动、首次沙箱预热失败）→ 允许一次有界同形状重试，不适用本方法
- read_file 失败回执提示『若文件刚被创建请重新 read』且确有对端进程可能在写 → 状态变迁事件后重新 read 是合法动作，不是变体枚举
- 用户验收硬性要求 git 直读本身（不接受回执替代，如必须给出 porcelain 全清单）→ 正确动作是升级/换环境/求证，而非用部署回执替代并宣称已核验
- 不存在任何权威回执通道供给该事实 → 『停止探测』不等于接受无知，必须转为向用户求证
- 目标文件其实在工具可达范围内、只是索引路径被规范化（ENOENT 但文件真实存在）→ 应走路径解析而非放弃直读，本方法不适用
