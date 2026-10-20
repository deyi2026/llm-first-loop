# 本地模型连续推理与共享压缩修复

本候选在 main bfe949a53 的隔离工作树中集成共享压缩合同/恢复修复，并补齐本地模型显式合同。没有按“本地/弱模型”推断能力，没有新增循环次数熔断、语义裁判或自动模型切换。

## 已证实的输入问题

- Qwen3.8 与 Ornith 的既有本地配置为 reasoning_replay=none，工具轮 reasoning 也在 provider-view 中省略。
- 当前加载的 Qwen llama.cpp 模板公开声明 supports_preserve_reasoning 和 supports_reasoning_effort；实际 apply-template 对照证实 none 丢弃历史思考、full 渲染原字段。
- LFL 的 temperature=0 覆盖了该后端 native temperature=1.0。
- 显式模型 effort map 在 auto 模式被遗漏，generation 与 token counter 均未投影；两个回归用例先 RED 再 GREEN。
- 旧字符估算重开缺陷为共享路径，Qwen/Ornith 均增加合同回归。

## 配置补丁

配置片段见 [local-model-reasoning-recovery-20261021.json](config/local-model-reasoning-recovery-20261021.json)。它是逐模型 merge patch，不是完整 Provider 配置，不含端点/凭据，不能替换整个 providers.local.json。

| 模型 | 修改 |
| --- | --- |
| qwen3.8-flash-next | full reasoning replay；显式 chat_template；low/medium 原样映射，high/xhigh/max 映射到已支持的 xhigh；temperature=null 交还本后端默认 |
| ornith-ai/Ornith-1.5-35B-A3B-MLX | full reasoning replay；temperature=null；不复制 Qwen effort/采样参数 |

null 在这里是模型配置的显式缺省值，Registry 不发送 temperature 字段。未选择该补丁的其他模型继续使用其原有显式合同。Ornith 作者模板读取 assistant.reasoning_content，但当前 MLX 模型未加载，不能用 Qwen 的验证结果替代 MLX 运行资格。

现有窗口 65536、输出预算 32768、provider 输入 cap、模型 ID、endpoint 和授权范围均未通过此片段改变。窗口、输出预留、工具 schema 和真实历史输入空间应分开观测。

## 实施与验证

- client._openai_chat_template_kwargs 在 auto 下仅应用显式模型 effort map，保持 enable_thinking 的后端默认所有权；off 不发送 effort。
- count_tool_schema_tokens 与 generation 共用该方法，缓存键包含模板 kwargs。
- 配置补丁经真实 Registry/ModelClientPool 装配回归，避免 default_client 的温度污染本地模型。
- 原始 Message、reasoning、tool_calls 保持不变；共享恢复通路仍提供 exact read。
- 本机模型任务、模板 SHA、收到的 request facts 和 usage 记录保存于隔离 worktree 的 data/local-model-recovery-20261021/。该目录是验证证据，不代表生产配置已激活。

## 运行配置生效与回滚

此次构建只在隔离数据目录生成配置候选，未覆盖生产配置。主线、push、部署和服务重启仍按原任务授权边界分别执行。

1. 复核 main、当前配置 SHA 与后端已加载模型/模板身份；漂移时重新生成差异。
2. 使用现有 provider_admin.mutate 的版本 CAS、文件锁和原子写入，仅合并 model_patches 指定字段；保留其他 Provider、默认模型、端点、凭据和预算。
3. 用当前生效代码的正常装配路径复核 resolved registry，再回读 backend request：reasoning 字段实际可见、mapped effort 到达模板、temperature 字段缺省。
4. 新 client 代码需要对应组件加载新版本；仅刷新确有需要的组件，并核验仍在运行的任务和健康状态。
5. 回滚时恢复已备份的精确配置版本及代码；保留完整会话、证据与原文，不清空会话。

配置源、进程解析状态和后端实际请求三者全部一致后，才声明运行生效。短任务成功不证明所有长任务永不重复。

## 协议依据

- https://huggingface.co/Qwen/Qwen3.8-Flash-Next
- https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B/blob/main/chat_template.jinja
- docs/DEVELOPMENT_REPAIR_SAFETY.md
