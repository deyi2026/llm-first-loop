---
method_id: precommit-self-scan-mirrors-gate-rule-surface-4a82394f3636
name: precommit-self-scan-mirrors-gate-rule-surface
description: 向带内容扫描闸（pre-commit/pre-push 类 hook）的仓库提交一批叙事型知识/经验卡、且卡片 evidence 引用真实环境细节（主机、ssh、内网 endpoint、用户名）时，提交前自检的判定力来自闸的规则面，而不是临场自造的 pattern：先从 hook 脚本、既往拦截回执里的正则或既有脱敏经验卡取权威规则集，对将入库全集跑同口径 grep（小批量叙事卡可直接读 evidence 行），命中即按仓库脱敏规则改写并复查清零后再 add/commit。自扫零命中只证明所含 pattern 内无命中，不证明闸会放行；若仍被拦，拦截信息即规则面，按其正则做全量定位，不只改被点名的那一个文件。
aliases: 提交前自检怎么和钩子扫描口径对齐, 自己扫没命中提交还是被隐私规则拦, 经验卡入库前先按闸正则查内网地址, 被 security scan 拦了别只改点名那个文件, 部署类经验卡入库脱敏自查
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:2e452d37-c246-40c6-9df5-b263eefb9cbb:1330:488e581387872909276d
evidence_refs: learning:learn:8b88cf8dd6ea
created_at: 2026-11-06T21:38:02.064663+08:00
updated_at: 2026-11-06T21:38:02.064663+08:00
---
## Trigger
准备把一批含真实环境证据（主机地址、ssh 命令、内网 endpoint、token 片段）的叙事型经验/知识卡提交进有内容安全扫描闸的仓库，且打算在提交前自检『无密钥/无隐私』时；或首次提交已被隐私规则拦截、需要决定修复范围时

## Discriminator
自检 pattern 覆盖是否与闸一致，这一点在提交前就可核：闸的规则面可从扫描 hook 脚本、既往拦截回执里的原样正则、或既有脱敏经验卡读到。另外，凡是记录真实部署/运维会话的叙事卡，其 evidence 行几乎必然引用真实主机与用户名，读任意一张即可命中私网地址；自己发明的『只扫密钥』扫描返回零命中，只证明该 pattern 集内无命中，不能当作闸的放行凭据

## Short path
- porcelain -uall 实测将入库全集，处置边界按 .gitignore 白名单与最近同类提交先例裁定（本集此步已做对）
- 提交前先取闸的规则面：读扫描 hook 脚本 / 既往拦截回执中的正则 / 既有脱敏经验卡，得到权威 pattern 集（密钥 + 私网段 + 真实用户名类）
- 用该 pattern 对将入库全集 grep（小批量叙事卡可直接读 evidence 行）；命中清单必须覆盖所有文件，而不是只看最显眼的一张
- 按仓库既有脱敏规则改写（内网地址末段掩码、真实用户名换占位符），并用同一 pattern 复查清零，保持复现指令语义可代入
- 再 add/commit，争取一次过闸；若仍被拦，把拦截回执里的正则当作新增规则面，补一轮全量 grep 后重提，不做无信息重试

## Stop conditions
- 将入库集在闸口径 pattern 下复查零命中，且脱敏改写不破坏卡片复现指令的可执行性（占位符可代入）
- 提交一次通过扫描闸，没有第二次同因拦截

## Verification
- 复用拦截回执或 hook 中的原样正则，对 staged 全集（git diff --cached 口径）再 grep 一遍，确认为零命中
- 提交与 pre-push 回执均显示安全扫描通过；若曾有拦截，确认后续无同规则重复拦截

## Counterexamples
- 仓库没有内容扫描闸、也无脱敏先例：硬找规则面是过度工程，轻量密钥自检即可，让版本控制本身当第一道检查
- 将入库集是机器生成的纯数据（度量 JSON、日志摘要），不含环境标识：读内容不增加判定力，直接依赖闸
- 闸规则在服务端不可读且无既往拦截可引：无法前置对齐，正确路径就是先提交让闸说话、把首次拦截信息当规则面（即本集的补救路径），不必硬找 hook
- 命中的确属测试样例且仓库有豁免登记机制（白名单类）：走显式豁免登记，而不是脱敏改写
