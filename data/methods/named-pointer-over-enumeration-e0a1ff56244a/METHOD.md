---
method_id: named-pointer-over-enumeration-e0a1ff56244a
name: named-pointer-over-enumeration
description: 核实/取证任务中，当所需事实缺失时，先检查最近一次在手的证据（成功页面的可见文本、失败回执的错误体）是否已显式点名下一步：或点名目标链接/章节，或点名失败的确定性成因及作用域。点名即行动：从工件原始源（raw markdown/HTML）机械提取 href，或按错误体提示立即行动（认证/换源类别取同一事实）；被证据排除的维度（UA 轮换、同义关键词重搜、URL 模式猜测）一律不做。本集按此路径可省去一次重复搜索、一次 404 猜测和约 6 次无效 UA 轮换，信息零损失。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:9bd2b826-af96-4acb-87be-49c2646f1725:8:19dd79748e316bba1d00
evidence_refs: learning:learn:1cdbdc93fa47
created_at: 2026-10-11T07:48:08.142126+08:00
updated_at: 2026-10-11T07:48:08.142126+08:00
---
## Trigger
网络核实/取证任务需要获取缺失事实（目标页面 URL、精确指标、star 数等），且最近在手的证据中存在显式命名：页面可见文本点名了目标链接/章节词条，或失败回执错误体点名了确定性成因及其作用域（per-IP rate limit、认证要求等）。

## Discriminator
两条当时已可见的事实：1) README 抓取正文的导航行已显示 'LHTB results' 词条——目标页链接存在于在手工件中，其 href 在 raw markdown 源中是字面可 grep 文本；2) api.github.com 的 403 响应体明写 'API rate limit exceeded for <IP>' 并提示认证可提额——按 IP 的确定性配额，UA/headers 轮换不在可行维度上。任一存在即应提取指针或按提示行动，而非枚举。

## Short path
- 明确缺失的未知量后，先扫最近在手工件：有无与该事实同名的链接/章节词条
- 有 → 从工件原始源（raw.githubusercontent.com 的 markdown 或页面 HTML 源码）grep href，直接得到目标 URL 并抓取
- 无链接但失败回执点名确定性成因 → 按回执自身提示行动：有 token 则认证重试；无则立即换源类别（badge 服务/HTML 页/镜像）取同一事实，不做同端点重试
- 抓取指向页后与原始待核声明交叉验证数值一致，停止

## Stop conditions
- 目标事实已从由在手证据显式导出的来源取得，并与待核声明交叉核对一致
- 在手证据中无任何点名指针、且失败非确定性成因 → 此时才进入宽发现/猜测/重搜

## Verification
- 最终 URL 可追溯到从在手工件提取的显式 href（provenance 一致）
- 指向页数值与原始待核声明互证（本集 0.4948 / 46 tasks / +17.3% 均吻合）
- 替代源数值与声明量级一致，并如实披露精度损失（badge 6.2k vs 声称 6224）

## Counterexamples
- 瞬时性失败（timeout/502/5xx）：重试与退避合法，本方法只适用于错误体点名的确定性成因
- 403 体说明认证可提额且手头有 token：正确动作是认证重试而非换源类别
- 在手工件并未点名目标（导航无对应词条、raw 源拉取失败、链接由 JS 构造不在 HTML 中）：URL 猜测与宽搜索才是正确回退
- 目标事实已完整包含在当前工件中：直接分析并停止，不做任何额外请求
