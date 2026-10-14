---
method_id: verify-integration-effect-on-declared-host-surface-099f129a8322
name: verify-integration-effect-on-declared-host-surface
description: 验证'组件/插件 X 是否已接入/生效'时，先读 X 装机副本的 manifest/README，确立四件事：它声明接入的宿主系统是谁、凭据与数据来源是什么、哪些文件是 X 自己的输出缓存、是否自带 status/doctor 第一方诊断命令。然后只在宿主系统自己的用户可见面上验证，或直接运行第一方诊断命令。相邻系统中同名词的 catalog/registry 查不到目标，不构成'未接入'的证据；X 的缓存文件缺失也不构成故障证据；JS 读不到 HttpOnly cookie 不等于未认证。诊断显示组件级未启用时先启用再复验，端到端确认一次即停。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:dbb11178-e3d2-4816-96e3-05377a07ca5b:124:1331a209175fcd31bc85
evidence_refs: learning:learn:dfe5c293f8f1
created_at: 2026-10-13T18:55:29.474321+08:00
updated_at: 2026-10-13T18:55:29.474321+08:00
---
## Trigger
需要判定某个已安装组件/插件是否'已生效/已接入'，且环境中存在多个暴露相似概念面的系统（多个 model catalog、config dump、registry），而组件自身的 manifest/README 与诊断命令可访问。

## Discriminator
在任何验证查询之前即可从组件装机副本读到的契约事实：README 声明目标宿主（如'将模型接入 DeepSeek Harness'而非当前会话的 registry）、前置条件写明凭据来源（'复用桌面 App 登录态'→~/.workbuddy 下那些 json 是自写缓存而非读取源）、并列出 status/doctor 现成验证子命令——这组事实一次定死'在哪个面验证、缺什么才算失败'。

## Short path
- 读 X 安装目录内的 manifest/README（用装机副本防版本漂移），解决未知量：'生效'指哪个宿主系统的哪个面、判据是什么。
- 若 X 自带 status/doctor，直接运行，一并回答'凭据是否可用'与'组件是否启用'两个未知量。
- 按诊断做最小修复（如默认 Off 的组件改为启用），再跑一次诊断复验。
- 在宿主用户可见面（如模型选择器出现预期分组）端到端确认一次，停止。

## Stop conditions
- 第一方诊断报告组件 Running 且凭据可用，且宿主可见面出现预期条目。
- README/诊断明确说明所观察现象属预期（所缺文件是 X 自写缓存、登录态来自外部 App、cookie 为 HttpOnly 不可由页面 JS 读取），缺席≠故障。

## Verification
- 把任一查询结果当证据前，先核对被查系统与 X 声明的宿主同名同源（路径/系统名一致），不一致则该结果不计入证据。
- 内部 status 通过后，仍在宿主用户可见面做一次端到端核对，防诊断检查层与用户可见层不一致。

## Counterexamples
- 用户明确问的就是那个相邻系统（如'LFL 目录里有没有 X'），此时该 registry 就是目标层，直接查即可，不适用本方法。
- 组件无 README/manifest/诊断命令（裸脚本、无文档），只能退回安装位置与依赖树做 provenance 追踪。
- 第一方诊断命令本身退化或与装机版本不符：改用端到端可见面核对，不要循环重试诊断命令。
