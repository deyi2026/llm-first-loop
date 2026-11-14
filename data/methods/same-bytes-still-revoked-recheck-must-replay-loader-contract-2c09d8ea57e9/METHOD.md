---
method_id: same-bytes-still-revoked-recheck-must-replay-loader-contract-2c09d8ea57e9
name: same-bytes-still-revoked-recheck-must-replay-loader-contract
description: 『启动钉指纹、每次动作重读比对』式撤销检查若只比内容，会被同字节身份攻击绕过：chmod 放宽、symlink 指向字节全同的另一份、nlink>1，内容不变但资格已破；FIFO/超大文件还会让重读阻塞或无界。判别事实：铸造该指纹的启动加载器本身带完整资格合同（O_NOFOLLOW+fstat 身份检查+有界单次读）。修复不是发明新检查，而是让重验点等价复用同一合同，任一失败即 revoked、重读自身不可阻塞；负测逐身份维度各一探针，另补一条经生产装配链（真实 loader/build_app）的端到端负测，手工塞 state 不覆盖 loader→fence。
aliases: 同字节换文件也要算撤销, 重验不能只比sha, 指纹比对要连文件身份一起查, symlink同字节绕过撤销检查, 重读配置防卡死防超大, 权限放宽了算不算还授权着
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:3204:ddabc081a43a00541192
evidence_refs: learning:learn:549c43f95ed2
created_at: 2026-11-14T08:19:59.867324+08:00
updated_at: 2026-11-14T08:19:59.867324+08:00
---
## Trigger
已存在或正要实现『启动时钉住安全指纹（如 sha256）、每次动作重读比对』的持续撤销/重验检查，且出现任一信号：审查实测同字节攻击绕过（chmod 放宽、symlink 换同字节文件后 revoked=False）、或重读路径可能阻塞/无界（FIFO、超大文件）。

## Discriminator
铸造该指纹的启动加载路径本身就是加固读取器，其源码可逐项列出全部资格条件与 IO 边界（O_NOFOLLOW、fstat 的 regular/owner/mode 位/nlink/size 上界、有界单次读）。内容相等≠资格相等：重验点与铸造点之间的合同强度差就是攻击面；修复规范与负测矩阵都应从这份已有源码清单导出，而非发明新检查或第二状态库。

## Short path
- 直读铸造指纹的启动加载器源码，逐项抄出它施加的全部资格条件与 IO 边界；这份清单同时是修复规范与负测矩阵
- 在重验点等价复用该合同：同一 open flags（O_NOFOLLOW|O_NONBLOCK）、同一 fstat 检查集、stat 先拒超大再有界单次读、与钉住指纹比对；任一失败=revoked/持久 stop，不新建第二状态库，不扩散调用点（同一入口收紧）
- 负测逐身份维度各一探针（chmod 放宽、unlink+symlink 同字节、hardlink nlink、FIFO、超尺寸），每探针同时断言重验函数与真实 spend/fence 路径都拒
- 补一条经生产装配链（真实 loader 经 build_app 自动注入，非手工塞 state）的端到端负测，覆盖 loader→fence
- 跑原有守卫/回归套件确认无回归；若合同无法等价复用，显式报 BLOCKED，不以弱化版收口

## Stop conditions
- 重验点与启动加载器逐项等价（flags、fstat 条目、读上界、指纹来源一致）且全部身份负测与装配链负测绿
- 证明授予物本无身份合同或存在文档化合法轮换机制，记录后按内容比对即完整合同

## Verification
- 机械对照重验函数与加载器的检查条目清单（flags/S_ISREG/owner/mode 位/nlink/size 上界/读长度）逐项一致
- 每个身份维度负测在纯函数层与真实 fence 层均断言拒绝
- FIFO/超大文件探针在有界时间内返回（不挂起、不无界读）

## Counterexamples
- 授予物从无身份合同（普通团队可读配置，任意权限均合法）：强加 0600/owner/nlink 检查会把合法状态误判为撤销，内容比对即完整合同
- 存在文档化的合法轮换/重签流程（operator 约定原子 rename 后重新授权）：身份或字节变化应走重新授权路径，而非自动永久 revoked
- 授予物是多文件/目录集合或远程服务而非单个 regular 文件：单 fd fstat 合同不适用，需另行定义资格面
