---
method_id: verify-named-artifact-existence-and-distrust-lookalikes-before-install-95e4a5987a92
name: verify-named-artifact-existence-and-distrust-lookalikes-before-install
description: 用户要求安装具名软件制品时，先用两个权威完备面把『装什么』降维成『存不存在』：①工具自产 help/manifest 的形态枚举，②官方 registry scope 名。目标形态在①中缺席、官方名在②中 404，本身就是可上报的发现（官方无此应用），任务应转为前提更正而非继续找安装物；此时仅官方 namespace 之外出现的同名包一律视为不可信 lookalike：只做元数据与 lifecycle 脚本的静态检查（bin 覆盖、quarantine 绕过、个人 repo 下载源、postinstall 副作用），绝不直接 install，并把风险与安全替代方案交用户裁决。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:136b8530-addf-4ead-941f-0a53520c54d8:310:cdf91d7bb1c0fcf5f9b0
evidence_refs: learning:learn:5585e4b01e2b
created_at: 2026-10-11T19:55:41.854584+08:00
updated_at: 2026-10-11T19:55:41.854584+08:00
---
## Trigger
用户要求安装/获取一个具名制品（如『DSH 桌面应用』）；当时可观察事实：工具自产 --help 已枚举其全部形态（web/tui/headless 等）且不含目标形态，或官方 scope 名（@org/product-target）在 registry 返回 404，同时官方 namespace 之外存在同名候选包。

## Discriminator
knowledge-at-time 三事实：①第 1 步 help 输出即枚举全部启动形态且无 desktop（由 commander 等框架自产=完备面，缺席是强证据）；②对已装 dsh 包全量 grep 'desktop' 为 0 命中；③npm 对 @deepseek-ai/dsh-desktop 返回 404，仅非官方 namespace 有同名包。任一成立即应把动作从『寻找/安装』切换为『核实存在性并准备上报前提问题』，无需更多本地路径/环境勘察。

## Short path
- 读目标工具自产 --help/manifest；未知量：用户所指形态是否属于该工具——本例枚举 web/tui/headless，无 desktop
- 由二进制路径直接得到官方包名 @deepseek-ai/dsh，据此查 registry 的 @deepseek-ai/dsh-desktop；未知量：官方是否发行桌面制品——404 即否
- 对 namespace 外同名包只做元数据审查（description 自述 Windows-only/『Do not npm install』、maintainer、repository）并静态解包读 lifecycle 脚本，不执行；未知量：候选是否可信、有无敌意或冲突行为
- 输出：前提更正（官方无桌面应用）+ 逐条风险证据（Gatekeeper 绕过自述、bin:dsh 覆盖会降级现有 dsh）+ 安全替代（本地 .app 包装官方 dsh web），交用户选择；不默认安装

## Stop conditions
- 官方 scope 名返回 200 且可核验 → 转回正常安装任务
- 两个完备面（help 枚举 + registry 404）已确认官方无此制品，且 lookalike 静态检查完成 → 停止搜索，输出前提更正与建议
- 静态检查发现安全敌意行为或 bin 冲突 → 立即停止，不安装，报告风险

## Verification
- 确认枚举确实是完备面：help 由框架自产（依赖可见 commander 等）、grep 覆盖包全量 files、404 来自官方 registry 而非镜像缓存
- 每条风险断言附可引用的静态证据（install.js 自述、bin 字段、tarball 文件清单），不凭包名相似度定性
- 最终『官方没有 X』限定为『已核查渠道内没有』；GitHub API 限流未核实的渠道要明示残留不确定性

## Counterexamples
- help/README 是手写营销文档而非框架生成的完备枚举 → 缺席不构成存在性结论，需另查 changelog/registry
- help 枚举含目标形态但本机缺失 → 是『未安装』不是『不存在』，本方法不适用，走安装路径
- 官方 scope 名 200 且由官方 maintainers 维护 → 正常安装任务，勿把官方包误判为 lookalike
- 用户明示『知道是第三方的，仍要装』→ 任务变为知情执行+备份/回滚计划，不再是前提核实
