# LFL CLI 使用与交互参考

> 本文随 2026-10-18 的 CLI 候选实现编写。是否已安装该候选，以实际构建和验收回执为准；开发分支不代表已经发布。

## 运行与输入

```bash
lfl chat "分析这段需求"
lfl chat --interactive
cat requirements.txt | lfl chat --stdin
lfl chat --message-file requirements.txt --model provider/model
lfl chat --session FULL_SESSION_ID "继续"
```

位置消息、`--stdin`、`--message-file` 三选一，不能与 `--interactive` 混用。
标准输入全文直到 EOF 只形成一个用户消息；stdin 与 UTF-8 文件都保留原始换行和空格，解码失败不做损失替换。
空白输入返回 2，不创建运行。没有明确输入且没有 TTY 时立即提示用法。
显式指定的会话不存在返回 1，不创建替代会话；显式启动选模失败时不使用默认模型继续执行。

`lfl chat --help`、`lfl help`、`lfl keys` 无需模型凭证。
所有命令均可使用命令级帮助，例如 `lfl delete --help`、`lfl event-migrate --help`、
`lfl check-install --help`。帮助与参数校验在环境准备、CLI 进程登记和 Engine 装配之前完成；
已知旧命令中的未知参数、缺少参数或类型错误返回 2，不会先启动模型或执行命令。
自由文本参数（例如搜索词、重命名标题、演进结果/核验说明）保留以连字符开头的内容；
这些位置没有可选开关，`-draft`/`--failed` 会作为文本处理。带真实选项的命令仍严格拒绝未知开关。

旧裸消息入口继续支持：`lfl "分析这段需求"` 仍是一次聊天消息；为避免兼容性破坏，
未知的顶层单词（例如 `lfl doctro`）仍按裸消息处理，不自动猜测为拼错的命令。
脚本和新用法推荐显式 `lfl chat ...`。已知命令命名空间中的错误子命令/参数则明确拒绝，
不会降级成聊天消息。旧 `list/search/delete/archive/unarchive/extract/fork/rename` 与
`evolve-*`、`event-*` 命令继续保留；参数由共享契约在副作用前验证。

## stdout、退出码和脚本

```bash
lfl chat --stdin --output json < prompt.txt
lfl chat --message-file prompt.txt --output jsonl > run.jsonl
lfl chat "hello" --plain --no-stream > answer.txt
```

| 退出码 | 含义 |
| --- | --- |
| 0 | 本次运行正常结束并交付；不代表语义任务必然成功 |
| 1 | 运行失败、不完整、取消，或指定会话/启动模型不可用 |
| 2 | 输入或参数错误 |
| 130 | 同步兼容路径被 SIGINT 终止 |
| 143 | 原生后台路径收到 SIGTERM；清理未确认时会明确标注 unknown |

默认文本 stdout 只交付正文；工具状态、模型、用量和诊断走 stderr。
`--no-stream` 只改变显示，不减少模型输出或跳过原生事件。
增强 TTY 的文字流在单一 CLI 输出线程逐块渲染稳定的 Markdown 标题、段落、列表；
未闭合代码块按原样逐行显示，未闭合段落在短暂等待后按原文继续输出，而不反复重画终端历史。
颜色遵守 `NO_COLOR`，控制字符只作为可见文字展示。`TERM=dumb`、纯文本、管道、JSON/JSONL
保持线性/机器输出契约。终端投影不回写会话原文；可用 `/render` 对已存回答重新完整渲染。
`--output json` 输出一个最终对象；`jsonl` 按序输出事件，schema 为 `lfl.cli/v1`。

JSONL 共有字段：`schema`、`type`、`seq`、`session_id`、`run_generation`。
事件包括 `run_started`、`text_delta`、`tool_started`、`tool_finished`、
`reasoning_activity`、`cancel_requested`、`result` 和 `error`。
`reasoning_activity` 只表示观察到推理活动，不包含隐式推理正文或虚构 token 数。
默认工具状态不展示完整参数；详情从用户显式请求的记录入口读取。

最终对象保留 `final_answer`、实际 `model_used`、用量、运行不完整/截断/投影失败、
取消原因、模型降级回执和校验说明。历史压缩本身不判为失败。
SIGKILL、断电或输出断管时，不能保证消费者收到最终对象；应按会话持久记录核实。

## 交互输入、布局和快捷键

默认增强内联模式保留终端原生 scrollback、鼠标选择和复制；只有用户明确
执行 /fullscreen 或 /browse full 时才打开可随时退出的只读全屏浏览器。
输入区随终端尺寸适配；高度小于 16 行时隐藏辅助状态行，内容不删除。
使用 `--plain` 或 `TERM=dumb` 进入基础输入；缺少编辑组件时明确提示降级。

| 动作 | 默认键 / 文字入口 |
| --- | --- |
| 发送 | Enter；补全菜单打开时先处理补全 |
| 插入换行 | Ctrl+J、Alt+Enter，或行末反斜线再 Enter |
| 显式多行 | `/input multiline`；Ctrl+X 后按 s 发送 |
| 单行模式 | `/input single` |
| 草稿外部编辑 | Ctrl+X 后按 e；`/editor` 使用 VISUAL/EDITOR，默认 vi |
| 历史与检索 | Ctrl+P/N、Ctrl+R；`/history` |
| 补全 | Tab / Shift+Tab；`/` 命令、`@路径` 文件路径 |
| 帮助/命令发现 | F1、Ctrl+X 后按 ? / p；`/keys`、`/palette` |
| 会话/模型/任务 | Ctrl+X 后按 l / m / t |
| 新会话 | Ctrl+X 后按 n；`/new` 或 `/clear` |
| 工具记录/复制 | Ctrl+X 后按 o / y；普通输入为 `/details`，运行期间按 o 进入只读记录浏览；`/copy` |
| 暂存/恢复草稿 | Ctrl+X 后按 b；`/draft` |
| 重绘 | Ctrl+L；`/redraw` |
| 取消 | 运行时 Ctrl+C 只请求取消本 CLI 拥有的准确代次 |
| 退出 | 空草稿 Ctrl+D；`/exit` |

普通问号是正文；Ctrl+B、Ctrl+S/Q、Ctrl+Z 不绑定为权限或任务动作。
增强输入支持括号粘贴；粘贴内容本身不提交消息。
在不能区分修改版 Enter 或中文 IME 确认键的终端，使用显式多行模式。
基础多行输入以单独一行 `.` 发送，以 `..` 插入一个句点。

历史在当前进程内按会话隔离，不默认把用户输入另存到全局明文历史文件。
`@路径` 补全仅插入路径，并不自动读取或上传文件；需要完整文本时使用
`--message-file`，或明确让模型使用已有文件工具读取。

增强 TTY 模式在当前 run 运行期间提供独立的下一轮草稿输入区。当前正文和工具事件继续流式显示；草稿只保存在 CLI 输入层，不修改本轮消息、会话历史或 run generation，也不会并发启动第二个 run。单行模式按 Enter 排队；显式多行模式按 Ctrl+X 后再按 s 排队。只有当前 run 到达终态后，草稿才会作为下一条用户消息提交。

运行中编辑下一轮草稿时按 Ctrl+C，会请求取消当前 CLI 所拥有的准确代次并暂存未提交草稿；它不会把草稿当成当前 run 的新输入。SIGTERM 会尝试关闭草稿 prompt、在进程内尽力暂存未提交文本并恢复终端；进程退出后不承诺草稿持久化。非 TTY、`--plain`、`TERM=dumb` 或缺少 prompt_toolkit 时退回顺序输入，不提供并行预输入；普通取消一轮仍不退出交互 shell。

运行中的下一轮草稿输入允许输入 `/browse`、`/browse goto 0`、
`/browse latest`、`/browse follow` 等只读本地命令，也可以按 Ctrl+X 后按 o
打开全屏记录浏览。此时命令不会排进下一轮消息或调用模型；退出后继续编辑
原草稿，当前 run 不暂停也不会多执行一次。记录浏览不读取外部工作区历史：
每次只从本会话的授权存储快照读取已持久化消息；新增已保存消息数与“已观测
流式更新次数”分开显示，后者不是新消息数。只有显式选择“latest”或“follow”
才把阅读游标推进到最新，阅读旧记录时有新消息也不会把位置抢走。

全屏浏览是可选 TTY 功能：q / Esc / Ctrl+C 只关闭浏览界面（不取消运行）；
j/k 切换记录、n/p 上下分页、h/l 横向看长 diff、d/i/c 切换存储 diff /
完整详情 / 正文、g 跳最新、f 打开/关闭跟随。增量内容发生变化时只以至多
每 100ms 一次的频率请求重绘，以免 10,000 个流式事件引发 10,000 次屏幕渲染。
全屏不写历史、不执行补丁、不上传文件；不满足 TTY 或缺少编辑库时，
使用 `/browse` 文字分页即可。

## 主题与用户显示设置

```text
/theme dark
/theme light
/theme high-contrast
/theme mono
/theme cancel
/settings
/settings bind view.tasks c-x a
/settings bind view.tasks
/settings reset
/settings save
```

主题包含 auto/dark/light/high-contrast/mono，采用终端背景与克制的提示颜色。
主题预览只在本 shell 生效；`cancel` 恢复最近保存的主题。
`/settings bind 动作` 后不带键序列表示禁用；同键或前缀冲突会拒绝。
文字命令保持可用。取消键、EOF、提交键和 Unix 流控/作业控制键保持保留。

/keymap 显示 29 个操作的默认按键、实际重映射、焦点和文字替代入口；其中
12 个 CLI 应用动作可以配置，其余仍由终端及输入库控制。/settings unbind view.copy
暂时停用一个动作；/settings keymap-reset 只重置键位而不改变主题，预览后
用 /settings save 持久化。Ctrl+X 是两次按键的应用前缀，等待期间显示提示；
前缀超时不执行半个动作。

Ctrl+X p、/palette、/commands 在增强交互终端提供可选择的命令面板：
箭头/Tab 导航、Enter 确认、Esc 取消。选中的命令先插入本地草稿，必须再次
提交才执行；若草稿已有正文，保留原草稿不覆盖。纯文本终端退化为文字命令列表。
@ 文件补全在工作区内最多提供 50 个候选，并显示目录/文件及字节大小；
不会读取内容、越过工作区边界或自动上传。

只有 `/settings save` 持久化到用户 `$XDG_CONFIG_HOME/lfl/terminal.json`，
默认 `~/.config/lfl/terminal.json`。原子替换用户设置，不读取项目目录中的键位配置。
显示设置不能修改 Provider、密钥、EXEC_MODE 或工具权限。

## 会话、任务和完整记录

```bash
lfl sessions list --json
lfl sessions search "关键字" --json
lfl sessions show FULL_ID --raw
lfl sessions export FULL_ID --format json --to session.json
lfl models --json
lfl identity --json
lfl identity --session FULL_ID --json
lfl config show --json
```

也支持 `session`、`model list`、`model show`、`status`，以及旧 `list/search` 别名。
查询无需完整 Engine 或模型请求，不登记进程、不注册新工作区。
读取采用现有工作区注册表映射及会话归属/删除标记；无法确定归属时明确拒绝。
`READ_PATH_SOURCE=event_log` 时使用原生事件重放，不以旧 JSON 冒充当前真相。

模型目录只展示已配置能力；`configured_model` 与 `actual_model` 分开。
`identity` 是只读诊断：显示当前查询使用的配置来源、canonical `runtime.toml`/`.env`
有效模型及来源、Python/venv/module 路径，以及可读取到的 Web/Feishu/Learning 服务
desired/live/stable 身份。服务 live 身份来自启动 manifest，stable 是已成功受控重启
回执；二者分别展示，不用旧回执伪装当前运行事实。查询不启动 Engine、不创建数据目录、
不发起模型请求，也不修复/重启服务。输出不包含密钥或完整 provider URL；配置的模型名
与服务 manifest 的 `model_ref` 是有意显示的诊断字段，环境中其他值不会被整体输出。

不带 `--session` 时，`actual_model` 明确为未观测；带 `--session FULL_ID` 时，只从该
工作区授权范围内的持久 assistant 消息读取 `LoopResult.model_used`，如实显示最后一次
有记录的实际生成模型，不以默认配置或会话覆盖猜测实际模型。

交互中可用：

```text
/sessions
/resume FULL_ID
/model
/model provider/model
/model default
/tasks
/transcript
/browse
/browse goto MESSAGE_INDEX
/browse next
/browse prev
/browse page
/browse back
/browse search 文本
/browse details
/browse diff
/browse content
/browse latest
/browse follow
/browse left
/browse right
/browse full
/fullscreen
/details MESSAGE_INDEX
/diff MESSAGE_INDEX
/raw
/render
/copy
/export json NEW_FILE
/export markdown NEW_FILE
```

`/tasks` 只读展示本会话 Goal、Task 和子 Agent 原生拓扑事实，不创建或取消子任务。
`/diff` 显示选中记录的原文，不推断工作区变更或自动执行补丁。
`/render` 用 Markdown 阅读最近回答，未知代码语言仍保留内容。
终端控制字符显示为可见转义；JSON 和导出保留原文。
复制只在明确请求时调用系统剪贴板；不可用时给出可选择的文本。
导出只创建新文件，已存在的目的文件会拒绝覆盖。

/browse 在当前会话按持久消息索引导航与搜索，并以 32 行分页、100 列横向窗口阅读正文、
完整详情或真实 diff；每页显示可核对的行号和后续页入口，不截断唯一原始来源。
当前会话与其他会话的浏览游标分开保存。/diff 只显示已持久化的真实 diff，
没有可读取的 diff 时明确告知缺失，不以“修改了若干行”的描述推断补丁。
/details、/raw、复制和导出仍提供原始记录保真通路。

## 审批、取消与恢复

已有 EXEC_MODE 审批回调由输入主线程接管；展示完整工具名和参数，默认拒绝，
只有明确 y/yes 才批准这一动作。Esc/EOF/中断表示拒绝，不扩大授权。
自动化和非 TTY 不弹审批，也不消费管道中的 y 来批准操作。

运行取消绑定 `session_id + run_generation`，旧代次不能取消后续新运行。
“取消请求已受理”、工具物理停止、Provider 计费结算是不同事实；
等待终态期间不会凭一个布尔 ACK 声称全部已停止。
终端恢复在 finally 中处理；会话继续不自动重放结果未知的副作用操作。

## 首用与分发

安装后遵循已有 `check-install → init → doctor` 路径；`doctor` 默认离线只读。
`--data-dir`、`--workspace`、`--config` 放在子命令之前。
运行态升级、回滚和服务操作继续使用已有安装工作流；
本 CLI 界面变更不自动重启服务或切换生产安装。

本指南描述 CLI 的用户可见命令与行为；可选只读全屏记录浏览已具备，
不表示高级侧栏、通知或自动升级执行已提供。实体输入法、Linux 原生终端及
SSH/多终端组合须以各自实测记录确认，不能据 macOS PTY 推断。
