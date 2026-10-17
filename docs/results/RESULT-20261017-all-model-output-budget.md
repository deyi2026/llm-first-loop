# 所有已配置模型输出预算调整（2026-10-17）

状态：28个启用模型均显式配置输出预算，25项提高、3项保持现有高预算；Web热重载完成，飞书和Learning受控刷新均succeeded。此单元只改运行配置及证据，未改源码/测试，未push。

## 原因与范围

用户新的DeepSeek事故：session `59688c5b-5ae5-42ee-9d63-23685fb569d6`、call `pcall:28ddcd9e0249884d65c39cc8f60d6fc4`，实际max_tokens16000；output16000/reasoning16000，finish_reason=length，已投递思考56020chars。前次只调整GLM-5.3，部分其他模型仍继承16000，因此本次逐模型调整。

仅修改`data/providers.local.json`的模型max_tokens。模型名、endpoint、输入/上下文限制、思考强度、timeout、全局默认及重试语义均保持原值。逆向恢复模型字段后的完整解析配置与原配置完全相同。使用现有文件锁、SHA CAS、原子替换和0600备份；重载在解锁后执行。

## 模型预算

| 模型 | 原有效预算 | 新预算 | 本次验证 |
| --- | ---: | ---: | --- |
| `cognilocal/ornith-ai/Ornith-1.5-35B-A3B-MLX` | 16000 | 32768 | 仅配置/目录校验；当前未加载 |
| `cognilocal/qwen3.8-flash-next` | 16000 | 32768 | 本地接口接受预算，短答成功 |
| `deepseek/deepseek-flash` | 16000 | 131072 | 本次解析与live registry校验；未单独发该变体请求 |
| `deepseek/deepseek-v4-flash` | 16000 | 131072 | 真实Web单轮完成，实际请求预算匹配 |
| `deepseek/deepseek-v4-pro` | 16000 | 131072 | 本次解析与live registry校验；未单独发该变体请求 |
| `glm/glm-5.3` | 65536 | 65536 | 预算保留；前次真实默认Web调用已验证 |
| `glm/glm-5.3-flash` | 16000 | 65536 | 本次解析与live registry校验；未单独发该变体请求 |
| `glm/glm-5.3-flashx` | 16000 | 65536 | 本次解析与live registry校验；未单独发该变体请求 |
| `minimax/MiniMax-M3` | 16000 | 131072 | 本次解析与live registry校验；未单独发该变体请求 |
| `minimax/MiniMax-M3.1-Flash-Preview` | 16000 | 131072 | 真实Web单轮完成，实际请求预算匹配 |
| `workbuddy/deepseek-v4-pro` | 128000 | 131072 | 代理接受预算，短答成功 |
| `workbuddy/deepseek-v4.1-flash` | 128000 | 131072 | 代理接受预算，短答成功 |
| `workbuddy/glm-5.1` | 48000 | 65536 | 代理接受预算，短答成功 |
| `workbuddy/glm-5.2` | 64000 | 65536 | 代理接受预算，短答成功 |
| `workbuddy/glm-5.3` | 64000 | 65536 | 代理接受预算，短答成功 |
| `workbuddy/glm-5.3-flash` | 131072 | 131072 | 代理接受预算，短答成功 |
| `workbuddy/glm-5v-turbo` | 64000 | 65536 | 代理接受预算，短答成功 |
| `workbuddy/hy3` | 64000 | 131072 | 代理接受预算，短答成功 |
| `workbuddy/hy3-x` | 64000 | 131072 | 代理接受预算，短答成功 |
| `workbuddy/hy4-preview` | 64000 | 65536 | 代理接受预算，短答成功 |
| `workbuddy/kimi-k2.6` | 32000 | 65536 | 代理接受预算，短答成功 |
| `workbuddy/kimi-k2.7` | 32000 | 65536 | 代理接受预算，短答成功 |
| `workbuddy/kimi-k2.8-preview` | 64000 | 65536 | 代理接受预算，短答成功 |
| `workbuddy/kimi-k3-1` | 32000 | 65536 | 仅配置/目录校验；代理当前未列出此别名 |
| `workbuddy/minimax-m2.7` | 48000 | 65536 | 代理接受预算，短答成功 |
| `workbuddy/minimax-m3` | 64000 | 131072 | 仅配置/目录校验；代理当前未列出此别名 |
| `workbuddy/space-bunny` | 128000 | 128000 | 仅配置/目录校验；代理当前未列出此别名 |
| `workbuddy/step-5-preview` | 64000 | 65536 | 仅配置/目录校验；代理当前未列出此别名 |

本地预算32768基于当前65536 context，未换模型或扩大本地context。WorkBuddy的space-bunny为不透明别名，保留既有128000，不推测其最大能力。代理接受预算只证明当前接口未拒绝该参数，不证明所有上游已实际生成同等长度。

## 激活与真实请求

- 配置SHA：`9fe185a77f367049ed0658a14ff341ef712ca00fc4c54bfbad245b78337d68f1`；Web目录effective28项预算逐一与持久化值相同，restart_required=false，默认仍为glm/glm-5.3。
- Web PID76553/source868431905保持不变，通过动态模型目录生效；其manifest里的旧配置hash是启动时快照，不能代替当前路由与实际请求证据。
- 飞书PID25059→4204、Learning PID25550→4736；各自既有service_control action等待空闲后succeeded/confirmed_ok，同一generation276/source868431905，manifest新配置hash匹配且默认max_tokens65536。未force，未为此再次重启Web。
- `deepseek/deepseek-v4-flash`：session `daf42c33-3164-4ad1-885f-2e5c9b8039c9`、call `pcall:24f95ebff9dfab2d6769e8264ec19bf2`，实际max_tokens=131072、timeout=120.0，success/stop、run.end=completed、1轮、无工具。
- `minimax/MiniMax-M3.1-Flash-Preview`：session `b883008b-8bf9-45f2-a881-b61ba02b8643`、call `pcall:a8ebf7a6b75017566ce0b6124064edf8`，实际max_tokens=131072、timeout=120.0，success/stop、run.end=completed、1轮、无工具。
- 两次Web验证是短答，未触及新预算上限。MiniMax首次并行入场session_busy且无provider call；确认无执行后仅重提该入场，最终每个session恰好一次provider transport。
- WorkBuddy当前可见的14个已配置模型最终均HTTP200有正文；共15次请求。GLM5.1首次探针未带其既有medium强度，代理默认值触发400；按既有medium补测成功，没有修改强度配置。
- 本地Qwen32768短答成功；Ornith未加载。WorkBuddy四个未列出的旧别名：`kimi-k3-1`、`minimax-m3`、`space-bunny`、`step-5-preview`，保持原身份并明确未资格验证，不替换模型。

## 证据与边界

回执：`docs/governance/receipts/RECEIPT-20261017-all-model-output-budget.json`。原始配置备份、探针和脱敏运行事实位于ignored `data/all-model-output-budget-20261017/`；备份含本地连接配置，不纳入Git。

官方边界参考（2026-10-17核对）：DeepSeek上限393216，本次选131072；MiniMax M3建议131072/上限524288；GLM文档默认65536/最大131072。代理自定义别名以本代理接受情况为证，不把其他后端能力当等价事实。

来源：

- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/api/list-models/
- https://platform.minimax.io/docs/api-reference/text-chat-openai
- https://docs.bigmodel.cn/cn/guide/start/concept-param
- https://cloud.tencent.com/document/product/1823/130051

本次为配置与运行态操作，完成解析、逆向diff、28项live registry核对、代表性真实请求和受控组件刷新，不重复执行完整R9。已有源码与回归/独立审查/原版R9证据见`RESULT-20261017-glm-output-budget.md`。长任务稳定性仍需后续实际运行观察；本次不宣称已证明每个模型长输出完整生成。
