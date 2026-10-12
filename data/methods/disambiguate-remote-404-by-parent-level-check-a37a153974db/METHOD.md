---
method_id: disambiguate-remote-404-by-parent-level-check-a37a153974db
name: disambiguate-remote-404-by-parent-level-check
description: 对远端分层标识（owner/repo/path、host/path）首次请求 404 时，先读 404 的形态而非立即换 URL 重试：目标服务本体返回的结构化 Not Found（自带 message/documentation_url、rate-limit 计数正常）已证明链路可达，未知量收窄为『标识符哪一级错了』。随后只做一次父级存在性检查（users/<owner> 或 owner 页）：父级也 404 ⇒ 名字本身错，立即转外部名称解析（名称+特征文件名搜索），不再用 HTML 页、control URL 等同义表示重复确认同一 404；父级 200 ⇒ 名字对，是私有/改名/分支错，在正确父级下定位资源。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:96d621f5-1690-49cb-8e4d-e05d75600791:8:5b0944e3cbee68513af8
evidence_refs: learning:learn:eb86a2479299
created_at: 2026-10-11T02:33:41.052951+08:00
updated_at: 2026-10-11T02:33:41.052951+08:00
---
## Trigger
需要抓取用户或上游材料提到的远端资源（如某 GitHub 仓库中的文件），手头只有名称/部分路径，首次访问返回 404，且不确定是网络被拦、分支不同、改名迁移还是名称拼写错误。

## Discriminator
404 响应的形态：由目标服务本体结构化返回（如 GitHub API 的 {'message':'Not Found','documentation_url':...}）即证明请求已到达服务端，网络/代理假设当场被否证，无需 control-URL 探测；真正未定的是标识符层级——GitHub 对『不存在』与『私有』都回 404，因此对父级（users/<owner> 或 owner 列表）做恰好一次存在性检查即可二分：父级 404=名字错，父级 200=资源级问题。

## Short path
- 首次 404 → 先读响应形态：结构化服务 404 ⇒ 排除网络/代理，未知量=标识符哪一级错；空体/超时/代理横幅 ⇒ 此时才做 control-URL 网络探测。
- 做恰好一次父级存在性检查（users/<owner> 或该 owner 的 repos 列表）。
- 父级 404 ⇒ 停止再戳服务状态，直接用 名称+特征文件名 做一次外部搜索，解析真实 owner/repo。
- 父级 200 ⇒ 名字对，列该 owner repos / 试其他分支定位资源。
- 解析成功后用一次 tree/meta 调用取准确路径与 size，再用显式回显 HTTP 状态的下载方式抓取，字节数对账后进入分析。

## Stop conditions
- 父级检查已把『名字错』与『私有/改名/分支错』二分，后续动作只服务胜出的分支。
- 外部搜索给出 owner/repo 与特征文件名同时匹配的唯一现名。
- 目标文件以与 API 元数据一致的 size/哈希成功落地。

## Verification
- 每个进入最终结论的远程事实都有带状态码的请求回执；不引用轨迹中无对应回执的『已确认』说法。
- 下载成功判据=显式 HTTP 200 且字节数与 tree/meta 报告一致，而非 curl 退出码 0（静默写出的 14 字节 '404: Not Found' 文件）。
- 同一 404 不在第二种表示（HTML 页、另一端点、带参数变体）下重复确认。

## Counterexamples
- 404 是空响应体、超时、522 或代理横幅（非目标服务自身回答）时，network-vs-resource 确实未定，control-URL 探测是正当的第一步，不应跳过。
- 父级不可查或标识符无层级（纯搜索结果 URL、裸文件名、短链）时，直接搜索解析，不硬套父级检查。
- 用户问题本身就是『这资源还在不在』：资源级结构化 404 已是完整答案，无需名称解析。
- 父级 200 且 repo 404：可能是私有仓库，结论应表述为『不可访问（不存在或私有）』而非『已删除』。
