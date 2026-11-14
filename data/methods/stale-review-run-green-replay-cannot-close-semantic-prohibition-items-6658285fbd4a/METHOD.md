---
method_id: stale-review-run-green-replay-cannot-close-semantic-prohibition-items-6658285fbd4a
name: stale-review-run-green-replay-cannot-close-semantic-prohibition-items
description: 外部审查方在自己（可能落后的）树上实跑并给出逐项失败清单与裁决，而当前树重放同款命令已全绿时：清单既不是待办也不是过期噪声。先把每项分类——夹具类（缺认证头、复用已停执行、调用不存在API）只需在当前树核实修复真实；语义类（裁决文本显式规定生产行为、禁止某捷径，如'不得为了过测试改为缺配置返回None'）不能因测试绿而销案，因为先前批次可能正是用被禁止的方式把测试改绿（让测试断言 fail-open 结果）。对语义类必须直读生产分支与测试当前断言，按裁决落地可区分状态（已配置但缺失=typed fail-closed 拒启动；未配置=default OFF），并新增走真实启动入口的测试。
aliases: 审查在旧树跑挂了但我这边全绿怎么办, 测试改绿但断言了被禁止的行为, 配置文件丢失时拒绝启动还是默认关闭, 父侧失败清单逐项核销, 缺配置 return None 是不是 fail-open, 外部裁决里的禁止项不能靠测试通过销案
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:3284:f4efda94899a8772b27d
evidence_refs: learning:learn:2f1caa8b2903
created_at: 2026-11-14T08:29:13.058976+08:00
updated_at: 2026-11-14T08:29:13.058976+08:00
---
## Trigger
审查方/父侧提供其本机实跑的逐项失败清单与裁决（含『不得用某捷径修复』式禁止项），而你当前树同款过滤命令全绿或失败集不一致（树在审查后已前进）。

## Discriminator
裁决文本中区分两类条目：仅描述测试自身错误的夹具类 vs 显式规定生产语义/禁止捷径的语义类。语义类的判别事实是当前树生产分支是否仍含被禁模式、且测试是否恰好断言了被禁结果（例：except OSError: return None + 测试 assert is None = 转绿掩盖生产 fail-open）。测试退出码对语义类条目没有证明力。

## Short path
- 当前树原样重放审查方的过滤命令，得出仍复现/已不复现分界（未知量：审查基于哪棵树、树前进了多少）。
- 逐项映射裁决文本分类：夹具类只核实当前树修复真实性（认证头真实到达、真实成功 read→arm、断言 durable row、新 root）；语义类不得因测试绿销案。
- 对语义禁止项直读生产代码对应分支 + 该测试当前断言：若测试断言的就是被禁结果，即『改绿测试掩盖生产洞』，按裁决修复生产语义而非维持现状。
- 把『路径已配置但 artifact 缺失』与『根本未配置』拆成可区分状态：前者 typed 异常/启动拒绝（确认调用点无 try/except 兜底），后者保持 default OFF。
- 新增/改写测试走真实启动入口（如 build_app 本身抛 typed 错误）而非仅 loader 函数；跑全量门禁，两类行为各自独立锁定。

## Stop conditions
- 清单全部为夹具类且当前树逐项核实真实修复：只回报状态差异（审查跑在旧树），不动生产代码。
- 语义类已按裁决落地，且新测试在真实启动路径上锁住行为，default-OFF 行为套件仍绿。

## Verification
- 确认未配置路径与已配置但缺失两类行为分别有独立测试锁定，互不掩盖。
- 确认 typed fail-closed 的传播点（如 app.state 赋值处）没有任何 try/except 或默认值兜底。
- 对照裁决原文逐条销项，每项给出『夹具已修 / 语义已落地 / 为何不需要动』的可核证据。

## Counterexamples
- 审查清单纯为夹具错误、无任何语义禁令且当前树全绿：直接回报状态差异即可，不应借机重构生产代码。
- 缺失的配置本就是可选功能（如 analytics 开关），缺失回默认关闭是正确 fail-safe——判别在缺失是否改变已授权或受限 session 的权限/预算状态，不改变则不适用本方法。
- 进程被可用性要求必须可启动并以健康端点上报降级时：启动即抛 typed 异常可能违反 SLA，应选裁决允许的另一安全分支（如持久 restricted-session deny）；本方法只强制『不得静默回退无预算/无限制路径』，不规定唯一实现。
