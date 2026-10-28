---
method_id: goal-url-redirect-as-login-oracle-9eb30c24b411
name: goal-url-redirect-as-login-oracle
description: 判断浏览器在某站点是否已登录、且任务目标本身是执行一个登录后动作（建仓/发布/打开管理页）时，不要绕道首页解析导航栏登录态：直接导航到目标动作的 auth-gated URL 并等待 URL 落定——落定 URL 等于目标 URL 即已登录且已就位可顺势执行；落定为 /login 类路径即未登录的确定性否定，立即终止浏览器分支、转向用户/凭据通道。一次导航同时充当探针与动作定位，把首页 snapshot + chrome 检索的弱证据分支整段省掉，搜索空间从『站点各处找登录迹象』缩成『读一个落定 URL』。
aliases: 网页登录没登录怎么看, 直接开目标页看跳不跳登录, 浏览器登录态探测, 跳到登录页说明没登录, 别在首页找登录按钮, 会话未登录怎么判断
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:080e4c70-20d4-4f4d-a9e7-adf018f5daa2:0:b2ee856e97ba35ad849c
evidence_refs: learning:learn:42726d35dcb1
created_at: 2026-10-24T17:02:30.578127+08:00
updated_at: 2026-10-24T17:02:30.578127+08:00
---
## Trigger
需要确认浏览器会话对某站点的登录态，且真正的下一步是执行一个需登录的网页动作（如创建仓库、发表内容、打开设置页）

## Discriminator
目标动作有确定的 auth-gated URL：导航后落定的最终 URL（或页内登录表单）一次性、确定性地回答登录态；而首页导航栏 chrome（有无用户名/登录链接）只是弱证据，快照解析与 evidence 检索常 miss

## Short path
- 确定目标动作的 auth-gated URL（如创建仓库页）
- 直接导航到该 URL，用 wait 谓词等最终 URL 落定
- 落定 URL == 目标 URL → 已登录，顺势继续执行原动作
- 落定 URL 为 /login 等登录路径 → 未登录的确定性否定，立即停止浏览器尝试
- 把未登录结论与缺失环节（建仓权限）连同替代通道（用户自建/先登录/提供 token）一次性上报用户

## Stop conditions
- 最终 URL 落定且非登录页：已登录，浏览器分支结束、转入执行动作
- 最终 URL 落定为登录页：未登录，立即停止浏览器尝试，不再扫其他标签页或解析首页 chrome
- SPA 延迟跳转导致 URL 未落定：再等一轮；仍不明朗才回退读 DOM 登录信号

## Verification
- wait 回执的 observed_value 即落定 URL，与目标 URL / 登录路径直接比对
- 登录态一旦由 redirect 判定，不再用首页快照、search_evidence 等弱证据『再确认』

## Counterexamples
- 目标页是公开页，未登录也不跳转：redirect 不构成登录态 oracle，需改用 /settings 或 whoami 类显式探针
- 站点用页内弹窗登录、不改 URL：仍只需一次导航，但判读信号是 DOM 登录表单而非 URL
- 导航本身有副作用（一次性流程/计费/触发邮件确认）：不得以导航当探针，先问用户
- 站点对未登录访问返回 404 而非跳登录：404 语义歧义，需先有已认证通道（如 ssh -T 成功）才能把 404 读成『对象不存在』
