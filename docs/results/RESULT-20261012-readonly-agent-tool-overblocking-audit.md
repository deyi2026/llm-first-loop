# SubAgent / 双 Agent 只读工具能力误拒绝：限定范围修复

## 判定

本轮不增加权限中心、不改变 Reviewer 只读身份，也不修改
生产 Provider、运行预算、任务准入或 macOS 特权服务。
查到一处确定性的只读误拒绝和一处批量检索性能损失：

1. safety.is_readonly_command() 传统的命令前缀和全文
   _WRITE_MARKERS 字符串匹配，不认识 rg、git show、
   git grep、git ls-files 等正常只读查询；
   grep 搜索内容带有 rm/chmod/kill 字样也被误当成写操作。
   此缺口只在显式 EXEC_MODE=readonly 时生效；默认 exec_mode
   为空，不能声称全部生产 Agent 已受此限制。
2. ToolRegistry._READONLY_TOOLS 已有 read_file，却不包含
   search_files；同轮多搜索被放入串行执行类别。
   search_files 只保存并发锁保护的派生路径事实，不修改
   用户工作区源文件。

## 已修改的界面

- 对 rg / grep / git show / git grep / git ls-files 增加明确
  只读命令形式识别；允许直接搜索，以及有界管道 head / tail。
- 新规则用 shell 词法区分真正管道与引用的搜索字符串。
  拒绝命令串接、重定向、命令替换、换行、任意下游程序；
  还拒绝 ripgrep --pre 外部预处理器与 Git --textconv、
  --ext-diff、--open-files-in-pager、git show --output/-o
  等可能执行外部程序或写文件的参数。
- 其他 shell 命令保留旧判定；EXEC_MODE=blocked、allowlist、
  写文件工具、CatastrophicGuard、工具执行日志不变。
- search_files 加入已有只读批量并行池，上限仍为 4；
  各调用仍过 Registry 的安全、预算、会话绑定与回执。

## 审查但不改动的权限

- read_file / read_attachment 已按运行上下文解析工作区路径，
  read_file 支持长文本分页与 immutable snapshot。
  未找到可以复现的同类路径误拒绝，不做无证据修改。
- SubAgentRunner 默认继承父工具发现面；当 requires.tools 显式存在时
  严格截断 child 的发现和执行白名单。这是现有 E4 明文授权契约，
  不可私自改为最低需求后让 Reviewer 获得超出声明的工具。
  后续如需改进，应分别命名需求字段与授权字段并保留父级只降不升。
- 浏览器 mutation / real profile 仍属显式能力门禁，
  不据此扩大生产浏览器写入能力。

## 事实、验收、发布条件

- 全部危险命令仅通过静态 is_readonly_command / Registry 判定测试，
  没有真正执行；覆盖正常源码查询、危险壳命令、外部预处理器、
  输出写入、其他 EXEC_MODE 与只读并行时的会话上下文继承。
- 生产 Web 首轮只读检查显示 2 个活跃会话，不能直接重启。
  仅允许既有 managed Web-only waiting_for_idle 发布：
  必须在真正重启前再次核验真实运行锁，禁止杀会话或强制覆盖。
- 候选必须在干净独立分支提交后过 R9、整树安全扫描；
  不清理 main 中其他任务未提交的 Method/Rules/Experience。

结论：只修有证据的只读工具误拒绝与串行化，不全面放权；
测试合格不等于功能已经生产发布。
