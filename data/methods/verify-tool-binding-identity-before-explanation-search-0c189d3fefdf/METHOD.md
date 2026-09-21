---
method_id: verify-tool-binding-identity-before-explanation-search-0c189d3fefdf
name: verify-tool-binding-identity-before-explanation-search
description: 当工具对环境的观察与用户对同一环境的直接陈述相矛盾时，第一未知量是“工具实际绑定/观察的是哪个实例”，而不是“为什么行为异常”。先沿可审计的 provenance 边（进程命令行中的端口/endpoint → 该端口的权威自述 /json/version 与 /json/list）枚举并鉴别所有活动实例，把异常观察归属到具体实例；只有身份核清后矛盾仍存在，才进入代码/会话历史/记忆层面的解释性搜索。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:138:16ec194459a4ecfd2937
evidence_refs: learning:learn:47dc29455b67
created_at: 2026-09-20T08:50:08.911141+00:00
updated_at: 2026-09-20T08:50:08.911141+00:00
---
## Trigger
工具观察到的环境状态与用户对同一环境的直接陈述矛盾（如：工具看到未登录页并断言“登录态失效”，用户说浏览器还开着且已登录），且该资源可能存在多个活动实例（多进程/多调试端口/多 profile）。

## Discriminator
进入歧路前已可见的事实：ps/lsof 输出里每个 Chrome 主进程命令行都带 --remote-debugging-port 与 --user-data-dir，即每个实例都有可直接查询的权威端点；且首个命令已示范 curl /json/version+/json/list 能返回 UA（区分 HeadlessChrome）与页面目标清单。用户陈述本身也直接否定“环境消失/登录失效”假设，指向身份错配。

## Short path
- 枚举该资源全部活动实例：ps/lsof 过滤 --remote-debugging-port/--user-data-dir（未知量：存在哪些候选实例）
- 对每个已发现的端口查 /json/version + /json/list（未知量：各实例是有头/无头、用哪个 profile、持有哪些页面）
- 核对工具当前绑定的 CDP endpoint/target 配置（未知量：工具的观察来自哪个实例）
- 归属匹配：持有异常观察（登录页）的实例是空 profile 无头残留，用户实例持有已登录 Gmail，矛盾由身份错配完全解释
- 验证后停止，给出结论与清理建议，不再向代码库/历史/记忆扩展搜索

## Stop conditions
- 全部带调试端口的实例已列出，且每个实例的 UA、profile 与页面清单已知
- 异常观察所属实例已确定，并与工具绑定端口的对应关系已验证
- 用户陈述与工具观察的矛盾已被实例身份差异完全解释

## Verification
- 持登录页实例的 /json/version UA 含 HeadlessChrome，且 ps 全量行显示 --headless=new 与测试/空 user-data-dir
- 该实例 /json/list 中的唯一页面 URL 与此前导航记录的 URL 吻合
- 用户实例端口 /json/list 含已登录 Gmail 目标，其余实例经 /json/list 逐一排除

## Counterexamples
- 机器上只有一个该类实例且就是用户那份：绑定身份无歧义，矛盾须在实例内部解释（cookie/session），不应做实例普查或代码搜索
- 矛盾对象不是环境身份而是代码/测试行为：枚举进程实例无关，应沿代码 provenance 边排查
- 工具自管浏览器生命周期（每次自行拉起、无共享实例）：绑定恒定，无需核对身份
- 用户未对环境做出可核对的直接陈述且工具观察自洽：缺少“矛盾”这一判别信号时，不应凭空怀疑绑定身份
