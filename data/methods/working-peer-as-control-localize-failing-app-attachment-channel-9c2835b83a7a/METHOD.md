---
method_id: working-peer-as-control-localize-failing-app-attachment-channel-9c2835b83a7a
name: working-peer-as-control-localize-failing-app-attachment-channel
description: 同一共享子系统（输入法/音频/代理等）下『X 应用能用、Y 应用不能用』的症状自述里，X 就是现成对照组：故障在 Y 侧专属挂接层（环境变量/启动 flag/平台协议通道），不在共享框架。用一次对比探针（正例应用、负例应用、服务进程的 /proc environ+cmdline）钉死差异；容器化进程的空 environ 是访问假象而非环境事实，改用 cmdline/desktop Exec/服务端日志作真值；修复落在 Y 的启动入口（用户级 desktop 覆盖、覆盖全部 Exec 动作），按单实例语义完整重启，以真实输入验收而非配置读回。
aliases: 浏览器打不了中文终端可以, 输入法部分应用失效, 有的软件能打中文有的不能, wayland 浏览器输入法不生效, linux 中文输入浏览器不生效, 对照能用和不能用的应用排查
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1174:ece7bf861242e21a3cc0
evidence_refs: learning:learn:73265fcfb921
created_at: 2026-10-29T12:57:46.504572+08:00
updated_at: 2026-10-29T12:57:46.504572+08:00
---
## Trigger
同一共享子系统（输入法、音频、代理、DNS 等）出现『部分客户端应用可用、部分不可用』的症状自述，正例应用与故障应用可能属于不同 GUI 工具链或运行形态（普通进程 vs 容器/沙箱内进程）。

## Discriminator
症状文本本身已携带对照：正例应用正在通过共享层工作 ⇒ 框架/守护进程/全局配置整体未被破坏；剩余故障空间只有故障应用的专属接入（IM 环境变量、启动 flag、平台协议通道）。该判别在任何探针之前即可用，不需要先检查或调整输入法框架。

## Short path
- 由正/负例对照固定假设：共享层正常，唯一未知量=故障应用的接入通道差异（不要去调框架配置）
- 一次批量远端探针：pgrep 确认服务进程在跑；对比正例应用、故障应用、服务进程的 /proc/<pid>/environ 与 cmdline（含容器 run-context），钉死差异（如故障应用无任何 IM 环境变量且原生 Wayland 缺输入法 flag）
- 若差异指向平台协议通道，一次验证服务端就绪（如输入法守护进程日志确认 wayland 模块已加载）→ 决定修客户端 flag 而非服务端
- 定位故障应用真实启动入口（容器应用读 entries 层 desktop 文件），写用户级覆盖并给全部 Exec 动作（主入口/新窗口/隐私窗口）加 flag，不动只读层
- 按单实例语义要求完全退出重启；ps 确认新 flag 真的在进程 cmdline 上；验收以用户在故障应用里实际打字为准

## Stop conditions
- 通道差异已定位且修复已写入故障应用全部启动入口，旧进程已完全退出
- 服务端就绪证据+客户端 flag 齐备后，剩余验证只能由用户实测完成，停止叠加探针

## Verification
- 重启后读取故障应用主进程实际 cmdline，确认新增 flag 在进程上而不仅在配置文件里
- 验收以用户真实输入为准；配置/D-Bus 读回通过≠图形会话生效
- 确认正例应用全程保持可用，修复动作未破坏共享层

## Counterexamples
- 所有应用都无法输入：无对照正例，方法不适用，应回到共享层（守护进程、全局环境、dbus）排查
- 正例应用靠回退/旧缓存在工作而共享层其实半坏，且对比发现两应用接入方式一致仍故障：此时对照结论失效，须转查共享层或更深的隔离面（容器对 dbus/socket 的阻断）
- 故障与通道挂接无关（如应用自身快捷键劫持了输入法切换键）：env/flag 对比无差异时应怀疑应用行为而非继续对比
- X11 会话下照搬 --enable-wayland-ime 之类具体结论：flag 是 Wayland 专属，可迁移的只有『对照差异定位』这层方法
