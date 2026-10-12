---
method_id: verify-interface-at-registration-before-asserting-3d0424761802
name: verify-interface-at-registration-before-asserting
description: 给用户或自己使用某条具体命令前，先在权威注册点核验其存在性：CLI 子命令/flag 由 argparse 的 add_parser/add_argument 封闭集合定义，可一次内容搜索枚举终结争议；不从兄弟接口（工具层动作、相邻模块）类比外推。本集教训：工具层有 restart 动作被泛化成 CLI 也有 restart 子命令，实际只有 publish/show/verify/worker。定义文件路径不确定时先按文件名搜索定位，不猜路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:907:a50fb1b48901ac57cf9c
evidence_refs: learning:learn:9928025241ea
created_at: 2026-09-19T12:21:20.300234+00:00
updated_at: 2026-09-19T12:21:20.300234+00:00
---
## Trigger
准备断言或执行一个可本地核验的接口用法（CLI 子命令、flag、endpoint、config key），而当前信念来自类比先验（另一层接口或相邻模块有类似动作），或首次读取定义文件时路径是凭记忆猜的。

## Discriminator
该接口表面是否由代码中的封闭注册集（如 main() 里连续的 sub.add_parser(...)）定义——若是，存在性争议可用一次注册关键词搜索（add_parser/add_argument/路由装饰器）解决；同时『工具层有动作X』不构成『CLI 有子命令X』的证据，两层是独立表面。

## Short path
- 明确未知量：命令/子命令 X 是否存在及其准确签名，而不是『大概有类似功能』
- 用文件名搜索定位定义文件（同命中多个时按模块职责选 CLI 入口），不猜相对路径；猜路径失败即立刻改为搜索
- 在该文件内做注册关键词内容搜索（如 add_parser），枚举封闭子命令集合
- read_file 注册行段，确认 X 是否在集合内及各参数要求（required/类型）
- X 不在集合内：明确否认并指向正确入口（如工具层动作），停止；在集合内：引用行号给出可执行命令，停止

## Stop conditions
- 注册闭集已枚举，断言已被具体文件+行号证实或证伪
- 已从权威定义取得准确用法，不再做类比性补充查找
- 同会话已有该命令的成功执行回执，可直接作为存在性证据

## Verification
- 最终断言能落到定义文件的具体行号（如 argparse 注册段）
- 跨层断言（工具层 vs CLI）各自对各自定义核验，不互为证据
- 给用户的命令中每个 flag 与 add_argument 定义一致（required、取值类型）

## Counterexamples
- 目标接口是外部二进制或第三方服务，本地无源码：权威来源是其 --help 或官方文档，grep 源码注册点不适用
- 该命令本会话已有成功执行回执：无需再核注册，直接引用回执即可
- 用户询问的是稳定公开知识（如 git 标准子命令）：无本地权威定义且先验可靠，逐条核源码收益低；仅当涉及本项目自有封装时才必查
