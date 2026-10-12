---
method_id: rescan-surfaced-hits-before-guessing-module-names-83285d6b29c9
name: rescan-surfaced-hits-before-guessing-module-names
description: 当『某符号/机制的实现在哪』成为下一个未知量时，本 episode 已检索到的输出（早期窄 grep 命中清单、调用点表达式）往往已经把候选缩到一两个文件。把已出现的证据当 provenance 账本重扫一遍，沿被点名的文件/接收者直达定义，而不是猜一个新包名再全量列举目录。本集在 token/auth grep 命中清单已列出 dsh-client-connection/lib/index.js、调用点 `connectionCtx.connection.authenticatedUrl(...)` 已点名接收者之后，仍去猜不存在的 dsh-web-server 并列出全部 62 个包，多绕两步才回到命中清单早已点名的模块。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:136b8530-addf-4ead-941f-0a53520c54d8:333:8601f70b61393a232932
evidence_refs: learning:learn:9fdb7c7ebb60
created_at: 2026-10-11T19:59:20.907532+08:00
updated_at: 2026-10-11T19:59:20.907532+08:00
---
## Trigger
在本地/已安装代码库中需要定位某个机制或方法的实现位置（如鉴权流程、某方法定义），且此前的工具输出中已出现过相关符号的 grep 命中清单或调用点表达式。

## Discriminator
摩擦发生前已可见的两条事实：早期窄 grep 命中清单点名了候选文件（dsh-client-connection/lib/index.js 在 token/auth 命中清单中），调用点表达式的接收者名指向同一模块（connectionCtx.connection.authenticatedUrl）——二者已把『定义在哪』从全部包缩到一两个文件，此时猜新包名/全列举是在扩大而非缩小空间。

## Short path
- 把用户问题转成一个明确未知量（网页登录如何完成），先读 CLI help 确认没有直接登录命令，排除 CLI 分支
- 做一次窄 grep（符号+子系统，如 token/auth×web-serving）拿到短命中清单，作为后续定位的 provenance 账本
- 需要定义位置时，先重扫已检索到的输出：命中清单文件名 + 调用点接收者名 → 直接进入被点名模块 grep 该方法
- 读定义并核对与调用点签名一致（authenticatedUrl(baseUrl) ↔ connection.authenticatedUrl(webUrl)；launch token → 签名 cookie → 303）
- 用最小实测验证用户侧行为（无 token=401 / 对 token=303+Set-Cookie / 错 token=401）后停止

## Stop conditions
- 已在被点名模块中读到定义，且该定义能解释用户可见行为
- 实测或与定义一致的静态证据已确认机制成立
- 命中清单仍有效（未被证伪）时，不为『可能还有别处实现』再枚举包目录

## Verification
- 定义处的方法名/参数与调用点一致（authenticatedUrl(baseUrl) ↔ connection.authenticatedUrl(webUrl)）
- 定义逻辑能解释实测结果：authorizeIndex 的 token→cookie→303 与 401/303+Set-Cookie/401 三条实测一致

## Counterexamples
- 此前输出从未出现该符号或模块（冷启动定位）：此时合理猜测命名（如 <feature>-server）或列一次包目录是正当的第一发现手段，本方法不适用
- 接收者是本地别名或鸭子类型、多个模块定义同名方法：接收者名不足以定位，应改为读调用文件的 import 语句
- 命中清单里的文件被证实与目标机制无关（如只是日志/analytics）：该 provenance 边断裂，才回退到更宽的发现手段
