---
title: LFL 复用 DSH 插件生态的落地路径（Node 桥 + MCP stdio + 热刷新）
scenario: "LFL 需要直接消费 DSH 插件生态（@deepseek-ai/* cordis 插件）而不经 DSH 进程；或任何\"用 MCP 桥接 cordis 插件到 Python 工具注册表\"的场景"
root_cause: ESM import 按脚本位置解析 node_modules，桥在 scripts/ 而 DSH 包池在 data/dsh-home/profiles/node_modules；cordis-plugin-loader 的 create 按包名动态 import 同样受此限制
solution: "① 桥放 scripts/dsh_plugin_bridge.mjs：模块解析必须用 createRequire(join(PROFILES_NM,'_bridge_resolver.js')).resolve(pkg) 或子路径绝对 import——直接 import 包名会从桥脚本位置解析失败（包池在 data/dsh-home/profiles/node_modules）；② 插件装配用 ctx.plugin(await import(module)) 而非 loader.create({name})——loader 按包名 import 同样解析不到桥外包池；③ 基础服务按依赖序装配 dsh-system-prompt→dsh-tools→dsh-sandbox-policy→dsh-fs-sandbox（dsh-tool-fs inject 依赖 tools/fs/systemPrompt）；④ MCP 暴露用 @modelcontextprotocol/sdk Server+StdioServerTransport，ListTools 映射 ctx.tools.schemas()（parameters→inputSchema），CallTool 调 ctx.tools.execute({name,arguments,callId,signal:AbortSignal.timeout(120000)})；⑤ Python 侧 mcp_client.py refresh_mcp_tools：关旧连→重连→重拉 tools/list→diff 注册/卸载（每服务器 fail-open）；⑥ MCP_SERVERS 为启动装配，改 .env 需重启进程生效"
evidence: EVO-20260819-f9e7ce23 落地：先 loader.create 全部报 Cannot find package；改 createRequire+ctx.plugin 后 mount 5 服务、tools/list 出 read/write/edit、真实调用 read 成功；refresh 幂等验证通过；test_mcp_client+registry 23 单测通过
tags: [DSH, MCP, cordis, 插件, Node桥, 热刷新]
source: {}
status: active
created_at: "2026-08-20T01:26:30.037964+08:00"
updated_at: "2026-08-20T01:26:30.037964+08:00"
---