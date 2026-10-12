---
method_id: locate-registry-data-via-loader-docstring-and-live-catalog-proof-a3ac1f105008
name: locate-registry-data-via-loader-docstring-and-live-catalog-proof
description: 接入/修改配置驱动的注册表（模型/provider/工具清单等）时，把“全仓找数据文件”换成“读加载器”：加载代码的模块 docstring / load_* 函数通常明文写出权威数据文件路径、优先级链和字段 schema。同时用运行时证据校验搜索结果：若某内容已被运行时目录/快照证明存在且被加载，而内容搜索报“无匹配”，判定为搜索范围/glob 假阴性，立即改走 loader 路径，而不是换关键词继续全仓枚举。定位后只读目标文件中现有条目作 schema 样板，写入后以运行时重载 + 最小真实调用收尾。本 episode 中该判断可省去对 factory.py/config.py 的绕行搜索与一次无效的 json/yaml 全局搜索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:204:fe28510145c558608ab0
evidence_refs: learning:learn:510dbcd7723c
created_at: 2026-09-28T17:31:01.741732+08:00
updated_at: 2026-09-28T17:31:01.741732+08:00
---
## Trigger
需要在配置驱动的注册表中新增或修改条目但不知数据文件位置；尤其当范围搜索对已被运行时目录/catalog 证明存在且被加载的内容返回“无匹配”时。

## Discriminator
两个当时已可见的事实：(1) 运行时模型目录已列出 minimax provider（api.minimax.chat/v1 + MiniMax-M3），证明其配置已被加载、必存在于某数据文件——因此后续 content=minimax 的 json/yaml 搜索“无匹配”只能是 scope/glob 假阴性而非不存在；(2) 代码命中已显示 providers.py 是 provider 语义/契约定义处，其模块 docstring 与 load_registry 明文写出加载优先级（MODEL_PROVIDERS env > providers.local.json > providers.json > L0 合成）与 ModelSpec 支持字段。

## Short path
- 抓取用户给出的官方文档 URL，取新模型可观察事实（context/effort 档位/reasoning_content 分离/思考不可关）→ 未知量：上游 API 行为。
- 用现有同类条目的窄查询（既有模型 id、registry 语义词）定位 registry 定义文件，而非宽搜 vendor 名（vendor 名在 tests/fixtures 泛滥）→ 未知量：条目注册在哪。
- 读该文件的模块 docstring / load_* 函数 → 未知量：改哪个文件、能写哪些字段，一次读取内解决。
- 只读权威数据文件中现有条目作 schema 样板 → 未知量：现存写法与单位。
- 写入新条目，用运行时重载 + catalog + 上游最小真实调用（含一个预期 400 用例）验证，一致即停 → 未知量：改动是否真实生效。

## Stop conditions
- 加载器文档已给出数据文件路径/优先级且现有条目 schema 已确认——停止定位，开始写入。
- 真实调用验证与文档声明一致（含一个预期失败用例）——停止。
- 搜索“无匹配”与运行时已加载证据矛盾时——立即改走 loader 路径，不再换关键词继续搜。

## Verification
- refresh_config 后 model_catalog 列出新条目且 reasoning contract 显示正确。
- 用现有 key 对上游 endpoint 做最小真实调用核对文档关键声明（本例：thinking disabled → 400/2013）。
- 写入位置与 loader 优先级链一致（local 快照与 seed 的层级关系明确，按需求选择或都写）。

## Counterexamples
- 运行时目录/catalog 中根本没有该 provider 且搜索无匹配 → “无匹配”是可信信号，应走正常宽发现，不适用假阴性判断。
- 用户已显式给出目标文件路径（“改 X 文件”）→ 直接编辑，无需读 loader。
- 目标条目应经 env JSON 内联注入（如 MODEL_PROVIDERS）→ 权威源是优先级链顶端的 env，而非数据文件。
- loader 是黑盒第三方库且无路径文档 → 需回退到目录枚举或运行时探测。
