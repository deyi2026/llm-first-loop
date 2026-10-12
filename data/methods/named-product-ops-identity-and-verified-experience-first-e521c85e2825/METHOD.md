---
method_id: named-product-ops-identity-and-verified-experience-first-e521c85e2825
name: named-product-ops-identity-and-verified-experience-first
description: 用户点名某产品（如"向日葵"）要求运维操作时，先用机器的权威注册表解析其本机真实身份：枚举已安装应用与服务管理器清单（macOS 用 launchctl/LaunchDaemons，而非 Linux 的 systemctl），一步确认真实进程/服务名（向日葵国际版=AweSun/oray）。身份解析后检索已验证经验记录，按记录中的确切 label、命令与日志验证信号执行。本集绕路：用猜测拼写 grep ps 得到假阴性→误判"未安装"→全工作区内容搜索→在 macOS 上跑 systemctl；而 search 命中预览已含 macOS/AweSun/launchctl 字样，launchctl 一步即可解析身份。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bc4d1b16-6f36-4f2a-ae59-5cf1e5e55966:0:2ded5995fcf4d8a20a67
evidence_refs: learning:learn:7e659620477b
created_at: 2026-09-23T09:23:57.748668+00:00
updated_at: 2026-09-23T09:23:57.748668+00:00
---
## Trigger
用户要求对某个具名桌面/客户端产品执行操作（重启/停止等）但未给出本机进程名或服务名；或按产品中文名/国内版名 grep 进程返回空；环境中存在带 verification_state 的经验记录库。

## Discriminator
对猜测拼写（中文名、单一品牌名）的 ps grep 返回空只证明这些拼写不存在，不证明产品未安装——用户点名要操作通常意味着已安装，品牌存在国内/国际改名（sunlogin↔AweSun，同厂 oray）。而已安装应用目录与服务管理器清单是小而权威的枚举，可一步解析真实身份；且工作区搜索命中预览中若已出现目标 OS 与工具名（macOS/launchctl），则 OS 专属命令选择已确定，无需再试其他 OS 的通用命令。

## Short path
- 收到具名产品操作请求后，先枚举权威注册表解析身份：ls /Applications 与 launchctl list（提示 root 域需 sudo）按厂商家族名过滤，而不是靠猜测拼写 grep ps 判定存在性
- 用解析出的真实身份（或并行）在经验/记忆库检索已验证记录并读全文，获取确切服务 label、命令序列、已知无效做法（如仅重启用户域不够）与成功验证信号
- 用当前机器的 plist 重新核对记录中的服务 label（防版本漂移），并读记录指定日志确认当前症状与记录一致、无会被重启中断的活动会话
- 探测 sudo -n；若需密码，先查既有凭据约定（临用临取、不留存、事后 sudo -k）并向用户索取，而不是在工作区文件里搜寻留存密码
- 执行记录中的最小命令集（root 域两个 daemon kickstart），以日志成功信号（P2P_CONNECTED/UDP 活跃）验证后停止并 sudo -k 清理

## Stop conditions
- 日志出现经验记录定义的成功信号（P2P_CONNECTED、UDP 端口活跃）且凭据缓存已清理
- 注册表枚举证明该产品确实未安装，转向向用户确认目标或安装路径
- 当前症状与经验记录不符（日志无对应挂死特征），停止套用记录并重新诊断

## Verification
- 实际执行的服务 label 与已验证经验记录及当前机器 plist 中的定义一致
- 操作后以日志/端口状态中的恢复信号为准，而非仅命令退出码 0
- 重启前已确认无活动远程会话会被中断
- 凭据约定被遵守：密码未留存、sudo -k 已执行

## Counterexamples
- 产品确以用户所称名字运行（如 Linux 上 sunloginclient 进程首查即命中），身份已解析，无需注册表枚举
- 用户指的是工作区项目/容器/云服务而非本机安装的桌面产品，注册表枚举无意义，应直接做工作区或服务发现
- 全新机器无任何经验记录，经验检索为空，应退回厂商文档与服务清单推导
- 经验记录中的服务 label 已随应用版本更新改变，必须以当前 plist 为准，不能盲信旧记录直接 kickstart
