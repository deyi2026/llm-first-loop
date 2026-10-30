---
method_id: pin-sdk-api-from-installed-source-before-writing-probe-code-589526d37397
name: pin-sdk-api-from-installed-source-before-writing-probe-code
description: 给本地已安装的第三方 SDK 新写探针/胶水代码时，先从两条在手的权威来源钉死真实 API——site-packages 里的 SDK 源码公开方法/事件面，以及仓库内对该 SDK 已通过测试的集成代码——再动笔，不要凭记忆拼方法名。本集凭记忆写 client.send 直接 AttributeError，被迫事后考古 SDK 源码，而这两条来源在写码前的依赖核查回执里就已确认存在。同一原则覆盖工具名：对任何『凭记忆的首调名字』，先对照本地权威清单（注册工具表/已装包源码/已验证 callsite）再调用。拿到服务端显式确定性鉴权错误码后，停止代码侧排查，转向凭据来源核对。
aliases: 猜SDK方法名报AttributeError, object has no attribute 探针写错API, 调库前先看site-packages源码, 别凭记忆拼SDK接口, 写SDK胶水代码先核对真实方法面, 探针脚本先钉API再跑
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:fd308b28-18c0-4929-b777-f1783be9298c:2207:619206a2d40009833826
evidence_refs: learning:learn:500fe6302e92
created_at: 2026-10-30T07:33:18.289898+08:00
updated_at: 2026-10-30T07:33:18.289898+08:00
---
## Trigger
要新写一段首次调用某第三方 SDK 的代码（探针脚本/集成胶水），且依赖核查已确认该 SDK 安装在本地可读路径（venv site-packages），或仓库内已有对该 SDK 跑过测试的集成代码；以及任何凭记忆调用未验证过的工具/接口名的场景

## Discriminator
写码前已在手的事实：①依赖核查回执已给出 SDK 的具体安装路径（.venv/lib/pythonX.Y/site-packages/<pkg>/，源码一次 grep 即得公开方法与事件绑定契约）；②仓库 bridge.py 等集成代码存在且有通过的单测（其连接模式即已验证的正确用法）。任一存在即把『凭记忆猜 API』缩成『一次定向读钉死 API』

## Short path
- 环境核查拿到 SDK 安装路径后，先一次定向 grep 该包主类的公开方法清单 + 事件绑定方式，钉死将调用的每个方法名
- 同时定位仓库内已验证调用点（bridge.py 连接段/官方探针脚本），复用其连接参数与已知修复（如代理劫持的 no_proxy 处理）
- 按钉死的 API 写探针，用确认过的解释器（.venv python）运行
- 探针回执拿到服务端权威结果；若为显式确定性错误码（如 invalid credential 类），立即停止代码/传输侧排查
- 转入凭据来源核对：抄的是哪个字段、由哪种模式签发，输出可勾选的核对清单

## Stop conditions
- 新代码中每个被调用的 SDK 方法/事件名都已在安装源码公开面或已验证 callsite 中确认存在
- 服务端已返回显式确定性鉴权错误码（如 invalid bot_id or secret）且网络层已证通——本地代码侧排查到此为止，剩余未知量只在凭据 provenance
- 探针成功完成握手与订阅——进入下一阶段真实收发，不再扩查 SDK 内部

## Verification
- 对每个将调用的方法名在已安装 SDK 源码中 grep 到定义（含签名）
- 探针的连接参数/代理处理与仓库内已通过测试的调用点一致
- 服务端错误码来自服务端回执而非本地异常，才可据此下『凭据错』结论

## Counterexamples
- SDK 未本地安装、只有在线文档或闭源二进制——本地读不可行，载体换成官方文档/类型存根，机制虽同但本卡前提不成立
- 调用面极小且失败回执本身即报出缺失方法名（AttributeError 即签名提示），throwaway 一轮试错成本低于读源码时，先跑再读可能更短
- 仓库 callsite 基于旧版 SDK 而当前安装版本已改名/移除方法——此时以当前安装源码为权威，不能只信 callsite
- 调用的目标是自研模块且签名就在当前会话已读过的源文件里——直接用已读内容即可，无需再发现
