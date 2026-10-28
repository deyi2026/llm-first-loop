---
method_id: measure-exposure-classes-at-remediation-parent-before-history-rewrite-ed8d23d1b91c
name: measure-exposure-classes-at-remediation-parent-before-history-rewrite
description: 报告称公共仓已推送历史含敏感信息（路径/IP/账户/密钥等并列标签）、需决定是否 filter-repo+force-push 重写历史时，第一个未知量不是『重写怎么做』而是『历史里实际有什么』：把报告的严重度标签拆成可机械检验的类别，钉住修复 commit 的父 ref 作为脱敏前权威基线，逐类穷尽扫描并验真命中（占位符 vs 真串），再按实测最弱暴露类别对比重写代价（全 SHA 改写、clone 分叉、fork 网络残留需平台 Support）。实测组成可推翻报告标签（如『IP/账户』实为仅本就公开的用户名），把不可逆重写降级为挂 P2 收档。修复 commit 的 diff 同时是扫描器的阳性对照：父树上该模式零命中必是扫描命令/作用域错，不是内容不存在。
aliases: 历史泄漏值不值得 force-push, 先扫脱敏前那版树再定级, 泄漏报告里 IP 账户说法要先验证, git 历史重写前做敏感度分级, 拿脱敏 commit 当阳性对照校验扫描
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:5005:ab190cf23e6acacdd2d5
evidence_refs: learning:learn:cd9e139dbcee
created_at: 2026-10-26T21:20:32.809598+08:00
updated_at: 2026-10-26T21:20:32.809598+08:00
---
## Trigger
决定是否对已推送公共仓历史做不可逆清理（history rewrite/force-push/密钥轮换）时，且泄漏报告把多种严重度标签（绝对路径/IP/账户/密钥）混列、未给出各类的实测组成

## Discriminator
修复/脱敏 commit 本身（message+stat）点名了它清洗了当前树哪些路径、并显式声明历史不在本批——其父 ref 即脱敏前基线，其 diff 里被改的文件集就是该敏感模式确实存在的阳性对照；报告中的『IP/账户信息』是待验证断言而非事实

## Short path
- 钉基线：取修复 commit 的父 ref（=脱敏前树），从其 stat/diff 提取受影响路径空间（如 experiences/）与『该模式确实存在』的阳性对照文件集
- 分类扫描：每类敏感物一条穷尽 git grep（真密钥模式 sk-/ghp_/Bearer；排除回环/内网/保留段的公网 IP；绝对路径与标识符变体），先扫受影响目录、后扫全树
- 扫描器自检：基线树上路径类若零命中而修复 diff 证明同类文件刚被改过，判定命令/作用域错误，重锚定文件清单后重扫——不把退化空输出读成『不存在』
- 验真：密钥类命中逐条区分占位符（如 'x'）与真串后才计入暴露
- 裁决：按实测最弱暴露类别对比重写代价，给 A（收档）/B（重写+残留声明）选项交数据所有者；实测计数与报告不符（如 54 vs 37 张）时先判断口径差是否改变结论，不改变则注明口径继续

## Stop conditions
- 每个被报告的敏感类别都已在钉住的基线 ref 上取得『存在+样本』或『穷尽覆盖下不存在』的结论
- 建议方向不再随更细扫描改变（如已确认零真密钥、零公网 IP、暴露仅为本就公开的账户名）

## Verification
- 负向结论必须来自该 ref 的全树穷尽 grep，而非部分读取或仅受影响目录
- 基线 ref 确认为修复 commit 的直接父且与远端一致，不是当前已脱敏树
- 计数与报告不一致时核对统计口径（树 ref/目录范围/变体模式）并显式声明是否影响结论

## Counterexamples
- 扫描发现任一存活真密钥/密码：立即轮换+重写，代价论证不适用，方法退化为只测不辩
- 仓库无外部 clone/fork（单人私有仓）：重写代价极低，即使仅用户名暴露也可能值得重写，成本侧论证塌缩
- 报告方已附确凿样本（如贴出泄漏的 key）：该类别免测，直接进入处置
- 暴露物在运行时日志/非 Git 持久层：钉 git ref 基线不适用，改查该存储的权威快照
