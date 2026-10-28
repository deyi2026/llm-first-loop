---
method_id: feature-parity-audit-anchor-named-mechanism-live-source-915ad1f1438c
name: feature-parity-audit-anchor-named-mechanism-live-source
description: 审计『外部工具的某功能是否值得自家 runtime 借鉴』时，不要用抽象功能词做宽搜：先把每个外部功能映射到配置/变更日志里已点名的第一方机制名，直读该机制的 live 源码文件（docstring+常量+关键行）拿行级依据。宽搜回执命中几乎全落在 vendored 依赖树或发布快照目录，即是走错入口的信号；无机制名的功能才做定向搜索并排除这些噪声路径。判定落三态：真缺口可借鉴 / 已覆盖更优 / 刻意更严勿抄。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:78fffae1-3786-4a53-9158-71e2847e5ab7:48:99ef1b22c9e374957e74
evidence_refs: learning:learn:fb45c6a944e0
created_at: 2026-10-16T09:02:58.381023+08:00
updated_at: 2026-10-16T09:02:58.381023+08:00
---
## Trigger
用户拿外部工具的若干功能问『我们这套是否值得借鉴』，需以自家代码现状为证据逐条判定，且仓库内含 vendored 依赖树（.venv/site-packages）与发布快照目录（.releases/）等噪声副本时。

## Discriminator
第一步读到的运行时配置已点名第一方机制（grant 变量、白名单等 ⇒ 存在 spawn/子代理机制及其工具名）；这已把『功能有没有』缩为『读该机制的权威源码文件』。随后抽象关键词宽搜的回执命中全部落在第三方 vendored 路径，进一步确认功能词搜索不是有效入口。两者在当时均已知，未用事后答案倒推。

## Short path
- 读运行时配置/状态，收集第一方机制命名（工具名、grant 环境变量、白名单），作为每个外部功能的映射锚点。
- 把『嵌套深度/能力声明』类功能映射到已命名的 spawn/子代理机制，直读其 live 源码文件（docstring + 常量 + 关键实现行），一次拿到深度上限、能力声明语义、默认拒绝策略的行级事实。
- 『fs 隔离』类缺口用机制内定向检索（如 workspace_root 赋值处）定位到具体行；确无机制名的功能（如侧问通道）才做关键词/文档搜索，并显式排除 vendored 与快照路径，miss 回执本身可作为缺席证据。
- 对 docstring 每条声明在同文件常量/实现交叉验证后，逐功能落三态判定（真缺口 / 已覆盖更优 / 刻意更严勿抄），全部有 live 源码依据即停。

## Stop conditions
- 每个被比较功能都有 live src/ 的行级证据并落三态判定。
- 真缺口已定位到具体文件行，足以写结构化建议提交人工审阅。

## Verification
- 引用行来自 live 源码树，而非发布快照目录或 vendored 副本（快照与 live 可能分叉）。
- docstring/注释的每条关键声明与同文件常量及实现代码一致（防文档漂移），最终判定至少有一条非注释代码行支撑。

## Counterexamples
- 功能在自家库确无任何已知机制名（真·新能力，如并行侧问面板）：关键词与文档搜索是合理入口，只需排除 vendored/快照路径，且不伪造 miss 结果。
- 仓库不 vendor 依赖、不留发布快照时，噪声源不存在，宽搜代价低，无需先做机制名映射。
- docstring 与实现长期漂移的旧项目：自述文档只能当线索，判定必须以实现行为或测试为准。
