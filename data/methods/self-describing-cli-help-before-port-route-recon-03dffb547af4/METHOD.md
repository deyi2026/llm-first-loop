---
method_id: self-describing-cli-help-before-port-route-recon-03dffb547af4
name: self-describing-cli-help-before-port-route-recon
description: 排查“能否直接控制/自动化本机已装应用”时，若应用包内发现第一方 CLI，应先一次性读完整 --help 及目标子命令的 --help，从权威自述文档拿到全部入口清单；不要先对内部端口盲猜路由（json/version、health、status 等连串 404 探测）或全量枚举扩展目录。一份自描述帮助文本可替代多次盲探；且 help 输出不要用 head 截断，子命令清单常在被截掉的尾部。仅当 CLI 能力不满足需求（如必须无头 API）才回退到端口/扩展逆向。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b98ea002-aed9-4ada-9e84-c45d1e4ca324:77:2e35a63fd96a0e5ee703
evidence_refs: learning:learn:1dc1ebfee2ae
created_at: 2026-09-25T03:54:41.773895+00:00
updated_at: 2026-09-25T03:54:41.773895+00:00
---
## Trigger
用户询问某已安装桌面应用/本地服务“能否被直接控制、派单或集成”，且机器上同时存在多个候选控制面（运行中进程、本地监听端口、应用包内可执行入口、配置目录）的可控性侦查任务。

## Discriminator
应用包内存在第一方可执行文件（如 Contents/Resources/app/bin/ 下唯一的 CLI），其 --help 是自描述的权威入口文档；而监听端口对根路径只回框架级 404（Cannot GET /），无路由表、无版本横幅——意味着前者一次调用即可枚举全部控制入口，后者只能靠盲猜收敛。另一条当时已知事实：help 被 head -70 截断，子命令（如 chat）恰在被截掉的尾部，导致需要第二次补读。

## Short path
- ps/lsof 定位应用进程、安装包路径与监听端口及其属主进程（未知量：存在哪些候选控制面）
- 扫描应用包内 bin/ 等自带可执行入口（未知量：是否随包发布第一方控制面）
- 存在 CLI 则一次性读完整 --help、不做 head 截断（未知量：全部入口/子命令清单）
- 对命中用户目标的子命令再读其专属 --help（未知量：能否注入 prompt/上下文文件并触发执行）
- 仅当 CLI 帮助确认不满足需求（如需无头/远程 API）时，才回头做端口路由探测或扩展归属定位
- 答案由“命名入口 + 其官方帮助文本”支撑，即停止侦察

## Stop conditions
- 完整 help 与相关子命令 help 已读，控制能力问题已被命名入口（或确证不存在该入口）回答
- 应用包内无自带 CLI，或 CLI 仅含开窗/打开文件等 GUI 选项 → 切换到端口/配置/文档侦察分支
- CLI 入口已确认但与用户目标不匹配（如要求无头而 CLI 必弹 GUI）→ 明确陈述该缺口后再决定是否继续扩查

## Verification
- 入口名、参数、模式必须来自该 CLI 自己的 --help 原文，而非对内部端口的猜测性探测结果
- 负面结论同样要有证据支撑：如“无无头模式”需完整 help 中无此项 + 关键候选路由 404 共同佐证
- 最终汇报中明确区分已验证事实与未冒烟验证的行为（例如子命令是否会自动开始执行）

## Counterexamples
- 应用不随包发布任何 CLI（bin/ 为空或不存在）→ 本方法无抓手，端口/配置/官方文档侦察才是主线
- CLI 帮助里只有窗口与文件参数、没有任何子命令 → 它不是自动化控制面，应立即回到端口或扩展路线
- 目标是 CI 级无人值守集成：即使找到会弹出 GUI 窗口的交互式子命令也不满足要求，仍需继续寻找 serve/远程 API
- 安全审计场景：未文档化的 WebSocket 端口本身就是调查对象，读 CLI 帮助与目标无关甚至误导
