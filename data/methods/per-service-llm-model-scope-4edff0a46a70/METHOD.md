---
method_id: per-service-llm-model-scope-4edff0a46a70
name: per-service-llm-model-scope
description: 把某个服务的 LLM 模型单独钉住（不动全局默认），用于「某通道必须用某模型 / 某 provider 对某服务不可用」的场景
aliases: per-service-model, 服务级模型覆盖, llm.wecom
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:fd308b28-18c0-4929-b777-f1783be9298c:3456:527146d41f927ec1eb84
created_at: 2026-10-30T11:33:45.864853+08:00
updated_at: 2026-10-30T11:33:45.864853+08:00
---
机制（仓库既有模式，非自创）：runtime.toml 支持「全局段 + 服务级子表」，resolver 复用既有服务作用域表 _SERVICE_SCOPED_SECTIONS（已有 semantic={web,feishu,wecom,learning}、knowledge_advisor={web}），字段沿用既有 TOML_SCHEMA（("llm","model") 已存在，无需改 schema），服务级值仍以 legacy 键（LLM_MODEL）承载，resolve_effective(service=...) 按服务选取。

三步：
1. src/llm_loop/runtime/resolver.py 的 _SERVICE_SCOPED_SECTIONS 增加 "llm": frozenset({<被授权的服务>})。只放被授权服务：写 [llm.其它服务] 会被 fail-closed（未知服务级 scope 报错），防误改他人模型归属。
2. runtime.toml（未跟踪/gitignored 的本机运维配置）在 [llm] 块**之后**加子表：
   [llm.wecom]
   model = "minimax/MiniMax-M3.1-Flash"
   TOML 顺序约束：子表必须晚于父表，否则解析失败。
3. 验证：resolve_effective(svc, {}, config_file='runtime.toml') 对每个服务看 .values['LLM_MODEL'] 与 .sources['LLM_MODEL']（应为 runtime_toml_service:<svc> vs runtime_toml）。

生效与持久性：release 树里没有 runtime.toml，配置永远取工作区根的 runtime.toml → 改完重启即生效，且跨重启/跨部署持久；代码侧改动需 commit+审查+push，服务进程 import 工作区 src（editable 安装）→ 重启即生效。

为什么不用「改全局 [llm] model」：全局默认归属其它服务，改它等于未经授权变更它们；服务级覆盖把爆炸半径限定在授权服务内，且日后改模型只改配置、不必再发版。

要点：TOML_SCHEMA 已有该字段时不必改 schema——只缺「作用域授权」这一行。误用伪造的 snapshot_ref 会被 edit_file 拒绝（须先 read_file(snapshot=true) 取真实 ref）。
