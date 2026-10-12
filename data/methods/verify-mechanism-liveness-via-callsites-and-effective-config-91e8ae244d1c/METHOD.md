---
method_id: verify-mechanism-liveness-via-callsites-and-effective-config-91e8ae244d1c
name: verify-mechanism-liveness-via-callsites-and-effective-config
description: Static evidence cannot prove a mechanism currently runs: defaults files are only the base layer, and nonzero cumulative counters prove past use, not present execution. Before asserting a pipeline is running or retired: (1) census its marker function in production source — definition-only hits with zero consumers mean the chain is retired and stats views are legacy; (2) read effective config from the live runtime snapshot, since service-level config layers override file defaults. Assert 'running' only when a real caller exists, effective config is on, and the live process reflects it.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0f0a5645-b407-4183-bd45-9c5d82003d93:20:f7f7fc8de9f2a6ac2ca9
evidence_refs: learning:learn:0655b551db3e
created_at: 2026-10-10T00:23:20.549969+08:00
updated_at: 2026-10-10T00:23:20.549969+08:00
---
## Trigger
即将对『某机制/链路当前是否在生产运行』下存亡断言，而手头证据只有静态类：配置文件默认值（.env 等）、累计使用/注入计数、统计视图或架构文档

## Discriminator
两类当时可见的事实可提前收窄：(1) 累计计数的时间戳已冻结数周（如 top_injected 的 last_inject_at 停在 8 月底而当前已是 10 月）——持续运行的链路不会数周不动，非零累计≠当前活跃；(2) 仓库内 eval/配置工件显示同一开关存在 runtime_toml_service:<svc> 层级取值——证明存在服务级运行时配置层，单读任一默认文件都得不到生效值

## Short path
- 把未知量固定为一句话：『机制 X 是否在当前生产路径被执行』，不为它引入额外假设
- 在 src 内对该机制的核心函数名做调用点普查，把命中分类为定义/转发 vs 真实消费方；零消费方 ⇒ 链路已退役，统计视图按遗留数据处理，该未知量即关闭
- 若代码路径存在，解析生效配置：不停在默认文件；依据配置加载代码/工件枚举配置层，直接读运行态快照或 live 进程的生效 scopes
- 三证一致（真实调用方 ∧ 生效配置开启 ∧ 运行进程反映）后才输出存亡断言，并注明每条证据的类别与来源

## Stop conditions
- 调用点普查完成：找到真实消费方，或确认仅有定义/转发（零调用方）——存亡未知量关闭
- 已从权威运行态快照读到目标服务的生效配置值及其来源层
- 断言所需三类证据（执行路径、生效配置、运行进程）已齐且互不矛盾

## Verification
- 断言必须可回指：grep 的完整调用点结果（含『仅定义』这一结果本身）、生效配置的值+来源层、live 进程状态，三者互不矛盾
- 断言『在运行』需至少一个非定义类调用方；断言『已退役』需零消费方且统计冻结时点与退役时点一致

## Counterexamples
- 目标只是掌握 API 签名/调用方式而非判定机制存亡——签名不确定时走 repo-api-discovery，不必查运行态
- 纯静态单层配置、无服务级覆盖机制、也无运行进程可查的项目：读默认配置文件即足够
- 机制经动态分发/反射/插件注册调用，grep 无法穷尽调用点：普查不下结论，应改运行时追踪或日志验证
- 任务是诊断『最近什么改动引发回归』：应走冻结 baseline + 单变量实验的根因流程，而非存亡断言
