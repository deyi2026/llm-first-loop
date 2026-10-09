# 审查报告：DESIGN-20261009-plugin-ecosystem-integration.md

审查方式：全文精读 + §1 代码基线逐项对照源码 + 官方规范引用实抓核验 + grill_me 追问式评审（3 轮）。
审查日期：2026-10-09。

## 一、总评

设计质量高，可以作为实施基线。三层事实全部核验通过：

| 层 | 核验方式 | 结果 |
| --- | --- | --- |
| §1 代码现状表 | 对照 `src/llm_loop/tools/mcp_client.py`、`skills/loader.py`、`introspection/tools_skill_files.py` 源码 | 抽查 6 项全中：协议固定 2024-11-05、initialize→tools/list 单页无 cursor、stderr=DEVNULL、无 id 通知忽略、schema 重建丢弃顶层组合约束（$defs/oneOf/additionalProperties）、重连重试一次、skills 单层扫描+简单 frontmatter、skill_load 返回 meta.body（frontmatter 原文不随正文返回；【2026-10-09 复核纠正】原表述"skill_load 回全文"不准确，见第六节） |
| MCP 双时代断言（D3） | 实抓 https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning | 一致：Modern=2026-07-28+ 逐请求 `_meta` 元数据；Legacy=2025-11-25- initialize 握手；`server/discover` 为 MUST；stdio 用 discover 探测+非现代错误回退；HTTP 用现代请求+检查 400 body |
| Agent Plugins 加载/错误隔离（D7） | 实抓 https://agent-plugins.org/client-implementers/loading-and-discovery | 一致：manifest 优先、$schema/name 必填、未知顶层字段与非对象 extensions 非致命、组件固定位置、最窄失败边界、不递归找嵌套 skills |

结论：**事实层可信，拷问发现的缺口集中在"对抗性内容"与"模型自主操作的滥用面"，属安全与验收层，不动摇架构。**

## 二、拷问发现的盲点（按严重度）

### G1【高】提示注入 / 内容污点策略全文缺失

grep 证实：全文无"污点"概念，"注入"仅指上下文注入与 factory 注入。设计防护了身份串用、路径越界、未知写重放，但没有覆盖**外部文本作为指令进入模型**这条最大攻击面：

1. 恶意 SKILL.md 正文 / 工具 description 指示模型调用 `send_feishu_message`、`web_fetch` 外传数据；
2. 工具 description 抢劫工具选择（"任何任务优先调用我"）；
3. MCP 返回文本中的交叉指令（外部服务器借结果文本操纵后续调用）。

**建议**：§8 增加 8.4"内容污点与注入防护"：结构化组件清单经校验后可影响装配；技能正文/工具描述/工具结果文本一律标注来源且**不得作为调用 outbound/凭证/安装类工具的依据**；外部文本内的指令性内容需显式用户或规则确认。并在 §12 增加 T26：注入 fixture（含外传指令的 SKILL.md 与工具结果）验证零外传。

### G2【高】模型自主安装的授权与配额未定义

"配额"零命中；§13 只裁决 scope。未回答：`extension_manage(install)` 是模型可自主执行还是需人工确认？结合 G1，恶意页面/包可诱导安装形成持久攻击面。

**建议**：待裁决表增加一行——首批默认"新源安装需人工确认 + 同 run 安装数/总包数配额 + 源域白名单（marketplace.json 声明域）"；canary 后再放宽。

### G3【中】规模上限有原则无数字

§10.2 只有"有限目录+发现入口"。验收无法判定过/不过。**建议给出硬数字**：目录初始注入 ≤N KB；单服务器工具数 >M（如 50）时只完整暴露 top-M、其余仅列名；单包组件数、description/SKILL.md/单次水合字节上限；超限行为=截断+如实标注，不静默丢弃。

### G4【中】重连代际与晚到响应错配风险

设计有 connection_epoch，但未写"重连后旧代 id 响应一律丢弃"。【2026-10-09 复核纠正】原文"现有 stdio 实现 `_next_id` 重连归 1"不准确：`_next_id=1` 仅在构造函数初始化（`mcp_client.py` L111），同一连接对象 close+connect 重连不重置该计数（`_start_process` L157-178 不触碰 `_next_id`；重连路径 L236-250），同对象内 id 单调不重复；新建连接对象才从 1 开始。风险重述：新连接对象 id 空间重置 + 晚到响应错配窗口仍然成立（未来 HTTP 同源重连尤甚），但依据是"id 空间可能重叠+晚到错配"，不是"已证实同对象重置"。**建议** §7.3 补：请求 id 命名空间含 epoch（或跨重连单调不重置）；晚到响应按代际丢弃并记 adapter 事件。

### G5【中】CapabilitySnapshot 并发写保护未说明（需确认）

InstallRecord 有锁+CAS+原子替换，但快照文件与 generation 的绑定未说明是否有同等保护；两服务并发 refresh 同一服务器时的行为未定义。**建议**补一句：快照写入同样走单写路径+CAS，读侧按 generation 取一致视图；若已有此设计则在文档显式化。

### G6【低，已在待定项】包数据回滚兼容

§13 已列"首批插件数据迁移契约与不兼容检测"。建议把默认值写实：旧包遇新格式数据默认拒绝启用并给出降级路径，而非未定义。

### G7【低】规范版本跟踪无 owner

§14 要求"实施时固定规范版本与 fixture"，但无人负责跟踪演进。**建议**待裁决表加一行：spec watcher 责任人+节奏（或 fixture 快照自动比对），规范断言变化走 adapter 失败而非静默兼容。

### G8【低】模型发现率不达标的分支未写

§12.3 用 8 个冻结场景验证，但未写失败分支与阈值。**建议**补：发现率/正确调用率阈值；不达标时的动作序列（改目录注入→改工具描述→回退注入侧方案）。

## 三、分期拷问（L1-Q6）

P0 独立成立，无争议。P1-A（标准包）与 P1-B（协议双时代/HTTP/OAuth）的顺序值得复议：若目标是尽早获得外部能力供给，MCP 生态是最大池子，P1-B + 现有 skills 已可用；标准包是分发治理收益。**建议**：§11 补排序论据，或对调 P1-A/P1-B（P1-B 不依赖包存储层）。

## 四、规范精度补充（实抓中发现的细节，建议并入 D3）

- 官方：era 判定是**服务器属性而非请求属性**；客户端 SHOULD 在 stdio 进程生命期/HTTP origin 内缓存判定结果，MAY 跨重启持久化、失效后重探。设计如未含此缓存规则应补。
- 官方：服务器对不支持版本必须回 `UnsupportedProtocolVersionError` 并列出 supported 版本，客户端据此重试或报错——建议作为 T 矩阵断言。

## 五、修订落点清单（可直接执行）

1. §8 新增 8.4 内容污点与注入防护（G1）；§12 新增 T26 注入 fixture。
2. §13 待裁决表增两行：安装授权/配额默认值（G2）、spec watcher（G7）。
3. §10.2 补硬数字上限表（G3）。
4. §7.3 补 id 代际隔离与晚到丢弃规则（G4）。
5. §9.1/9.2 显式化快照 CAS（G5）。
6. §13 包数据行补默认拒绝语义（G6）。
7. §12.3 补发现率阈值与失败分支（G8）。
8. §11 补 P1-A/P1-B 排序论据或对调（分期拷问）。
9. D3 补 era 缓存与 UnsupportedProtocolVersionVersionError 重试语义（第四节）。

## 六、复核修订记录（2026-10-09 第二轮）

1. 事实纠正一（G4 依据，见 L42）：`_next_id` 重置只发生在构造函数；同一连接对象 close+connect 重连不重置，同对象内 id 单调不重复，新建连接对象才从 1 开始。G4 建议本身保留（新对象 id 空间重叠 + 晚到响应错配窗口仍在），但事实依据已改写，不再以"已证实同对象重置"为据。
2. 事实纠正二（§一 核验表，见 L12）："skill_load 回全文"改为"返回 meta.body，frontmatter 原文不随正文返回"。代码依据：`skills/loader.py` `body = text[m.end():]`（frontmatter 之后正文）；`run_skill_load` 拼入的是解析出的 description，不含原始 frontmatter 文本。设计文档 §1 原本已如实标注该事实。
3. 配套说明：G2 建议原文"源域白名单（marketplace.json 声明域）"表述有歧义，第二轮审查已在设计文档 §13 改正为"白名单仅由可信宿主配置或用户显式授权建立，待安装包自带的 marketplace.json 域声明只作待核验声明、不构成白名单条目；已有适用授权复用"。本报告 G2 原文保留作历史记录，语义以设计文档为准。
