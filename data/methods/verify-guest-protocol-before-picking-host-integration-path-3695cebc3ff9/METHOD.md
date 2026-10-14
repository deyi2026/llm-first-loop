---
method_id: verify-guest-protocol-before-picking-host-integration-path-3695cebc3ff9
name: verify-guest-protocol-before-picking-host-integration-path
description: 回答『能否把外部系统 X 接入宿主系统 Y / 能否把 X 的某通路借鉴到 Y』这类跨系统集成可行性问题时，先确定 X 实际暴露的协议（读 X 的已安装实现：包元数据、端点/认证字面量、base URL 构造），再与 Y 注册表标准条目形态比对；协议命中标准契约时，接入从写代码降级为改配置，只有协议证伪后才需要调研 Y 的特殊扩展机制（surface/浏览器类 provider）。反之，先调研 Y 的特殊机制会把答案形状猜错，产生一整段对最终路线无效的验证动作。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:dbb11178-e3d2-4816-96e3-05377a07ca5b:251:b01f99680a68180138ba
evidence_refs: learning:learn:0cb099699fc5
created_at: 2026-10-13T18:59:48.894094+08:00
updated_at: 2026-10-13T18:59:48.894094+08:00
---
## Trigger
用户提出跨系统集成/借鉴可行性问题（『X 能不能接进/借鉴到 Y』），且 X 的本地安装实现可获取、Y 的注册表/模型目录已有一个初始回执；尚未确认 X 的协议形态，正要选择从 Y 的哪条接入路径（配置项、代码注册 provider、特殊 surface 模块）开始核实。

## Discriminator
进入机制选择前已可见：Y 模型目录的首个回执显示其标准食谱全部是 OpenAI 风格 HTTP 条目（base_url 指向 /v1 型端点 + api_key，本地服务与公有 API 同构），即『OpenAI 兼容 HTTP』是 Y 的默认接入契约，特殊 surface 机制只为无 API 目标保留。因此第一未知量应设为『X 是否也暴露 OpenAI 兼容 HTTP』——本集这一判别直到很晚 grep 出 completion 路径 + Bearer 才兑现；此前多个动作花在核实 browser:// 特殊机制的实现上，最终答案明确承认那不是要走的路。

## Short path
- 未知量1：X 的通路暴露什么协议？按常规安装/配置约定路径（应用主目录、profiles 下的插件目录等）直接定位 X 的本地实现；禁止先做全盘 find（本集全盘 find 60s 超时，收窄后一跳命中）。
- 对 X 的包元数据与代码做机械 grep：URL 字面量、Authorization/Bearer、completion 路径、base URL 构造 → 提取上游主机、认证方式、端点形态。
- 若得到『OpenAI 兼容端点 + Bearer token』类证据 → 与 Y 目录标准条目形态逐字段比对；命中即判定为配置级接入，停止任何机制侧调研。
- 只在 Y 侧读一处标准配置样例确认 schema 能容纳该形态（base_url/api_key/模型字段），不深读 Y 的特殊扩展实现代码。
- 把剩余工作转为运营缺口清单（token 获取与刷新、端口/生命周期、成本档、reasoning 语义、出网可达），逐条标注未验证后停止。

## Stop conditions
- X 的协议已由其自身代码字面量（端点+认证头）确定，并与 Y 现有条目类匹配 → 停止机制调研，转向运营风险枚举
- 协议证伪（X 无任何 HTTP API 面、仅浏览器会话可用）→ 停止协议探测，此时才去读 Y 的 surface/特殊 provider 机制
- 常规约定路径找不到 X 本地实现 → 才允许扩大文件系统范围搜索

## Verification
- 决定性协议事实必须来自 X 自身代码/配置的端点、认证头、URL 构造字面量，不得从 Y 侧机制类比或猜测得出
- 断言『只需改配置』前，确认 Y 至少一个现有条目与提取的协议形态同构（字段级 schema diff）
- token 生命周期、reasoning 控制语义、成本档、网络可达等未实测项在最终答案中显式标注 unverified

## Counterexamples
- X 确实没有 API 面（网页版仅靠会话 cookie/HttpOnly 认证可用）时协议检查失败，Y 的浏览器 surface 类特殊机制恰是正解——此时『先调研特殊机制』的原顺序反而是对的，不应套用本方法
- 任务目标是修改 Y 的注册机制本身（如为 registry 新增 provider 类型/字段）而非把 X 接进去，此时应先读 Y 的注册代码，本方法不适用
- X 未在本地安装、只有远程文档或需抓包才能确认协议时，『grep 已安装实现』不可行，需改用文档/流量证据，短路径第 1-2 步失效
