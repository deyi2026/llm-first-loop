---
method_id: capability-verdict-registry-schema-firstparty-scope-7f028740bd57
name: capability-verdict-registry-schema-firstparty-scope
description: 在自有运行时/仓库里被问『X 支持 Y 能力吗』（如大模型支持实时音频吗）时，先拆成行业面与本机面。本机注册面的第一证据是已在手的 catalog/registry 回执：按条目字段 schema 与标签语义判定（全部为 chat /v1 端点、标签仅 [reasoning]/[multimodal=图像] 且无音频/实时字段即未注册；负结论读到 complete）。实现面只搜一手面（根级带日期 .md、docs/、src/、webui/src），并把命中路径前缀当机械噪声分类器：.venv*/site-packages/node_modules 命中一律不是本项目证据，应收窄 scope 而非换词重搜全库。行业面直抓厂商权威文档（沿用 canonical-host 枚举方法）。本集 22 次调用约可缩至 6 次。
aliases: 全库搜能力词全是依赖包噪声, venv node_modules 命中要排除, 多模态标签不等于实时语音, 本机模型有没有实时音频怎么查, 是非题拆行业和本机两面, 模型目录字段判能力
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:963f2568-3f7b-47ed-980e-eea2b5783a95:0:1dffc800f9ee4b7557d5
evidence_refs: learning:learn:6f8f20fcc111
created_at: 2026-10-23T12:58:37.614512+08:00
updated_at: 2026-10-23T12:58:37.614512+08:00
---
## Trigger
用户在自有环境/仓库内问某能力是否存在或被支持（『支持 X 吗』），答案同时取决于厂商是否提供与本机注册/实现现状；或：对仓库做能力词内容搜索时首批命中大量落在依赖缓存目录

## Discriminator
两条当时已在手的事实：1) model_catalog 回执的条目字段 schema——全部为 OpenAI 兼容 chat /v1 端点，标签仅 [reasoning]/[multimodal] 且 multimodal 与视觉模型共现，schema 中不存在音频/实时/流式字段，本机注册面当时即可判定；2) 首次全库内容搜索的命中路径前缀全部是 .venv-da/.../site-packages/langsmith/——依赖缓存命中可机械判为噪声，不是一手证据

## Short path
- 把问题拆成两个未知量：行业是否已有原生实时音频接口；本机会话模型/仓库是否具备实时音频链路
- 本机注册面：直接用手头 model_catalog 回执按字段 schema+标签语义判定『未注册实时音频模型』；仅当 coverage 不完整时补页读到 complete（负存在结论门槛）
- 本机实现面：内容搜索收窄到一手面（根级带日期 .md、docs/、src/、webui/src，排除 .venv*/site-packages/node_modules）→ 命中当日设计文档的 E01-E08 证据表（只有 SpeechRecognition 单次听写，无 getUserMedia/AudioWorklet/RTCPeerConnection）；必要时一次同 scope 符号 grep 复核
- 行业面：直抓一个厂商权威文档（如 OpenAI Realtime 官方指南）取 GA 事实；第二厂商抓取失败即按引用处理，不循环重试
- 按三层能力分类（音频理解/流式 TTS/原生双工实时）+本机结论+已核实 vs 未核实分栏作答，停止

## Stop conditions
- registry 已读到 complete 且一手设计文档/源码检索给出与之一致的实现面结论
- 厂商权威文档已给出至少一个 GA 的原生实时接口实例即停，不逐一核对全部厂商
- 同 scope 一手搜索连续 miss 时声明覆盖边界，而非扩大到依赖缓存目录

## Verification
- 复述 registry 回执中的具体字段/标签作为『未注册』依据，并确认 coverage=complete
- 本机结论能同时落到一手文档行号/符号检索与 registry 字段两层证据
- 答案中所有厂商事实标注来源（官方文档直读 vs 二手引用未核实）

## Counterexamples
- 用户只问行业面（如『OpenAI 支持实时音频吗』）且无本机上下文→完全不碰仓库与 catalog
- 依赖包本身就是询问对象（如『langsmith SDK 记不记 audio tokens』）→ site-packages 命中恰是信号，不可过滤
- catalog 已知陈旧或不是实际服务路径（runtime_identity unknown 且有可疑）→ schema 读数只是声明，需按 live-contract-probe 方法最小实测后才能下能力结论
- 项目没有任何带日期设计文档→一手文档搜索 miss 属正常，回退到一手源码符号检索即可，不必翻依赖缓存
