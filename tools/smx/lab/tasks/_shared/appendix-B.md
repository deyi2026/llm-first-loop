## 可选工具：smx（语义 shell 执行器）

你可以在普通 shell 命令之外使用 smx（可选，非必须）。它执行 shell 命令并返回语义回执：文件系统变更 diff（created/deleted/modified，省去事后重跑 ls 验证）、管道各段退出码链、stdout/stderr 落盘路径；另提供 `wait` 一等等待动作（条件谓词由程序轮询，命中退出码 0，超时退出码 2）。

位置（绝对路径，用 python3 调用）：`{SMX}`

```bash
# 前台执行 + 前后快照 diff：回执直接列出本次命令造成的变化，无需再 ls 一遍
python3 {SMX} exec 'mkdir -p out && cp a.txt out/' --root .

# 等待条件成立（四种谓词：--file-exists / --file-gone / --file-contains PATH TEXT / --port-open N）
python3 {SMX} wait --file-exists out/done.flag --timeout 60

# 后台启动 + 收尾：collect 给出该后台任务时间窗内的文件变更 diff 与退出码链
python3 {SMX} bg 'python3 worker.py' --root .
python3 {SMX} collect <RUN_ID>    # RUN_ID 见 bg 回执首行

# 重放已存回执
python3 {SMX} show <RUN_ID>
```

说明：回执落在 `<cwd>/.smx/runs/<RUN_ID>/receipt.json`，stdout/stderr 也已落盘（回执里有路径），需要时可随时读回。`changed` 是净状态 diff（窗口内瞬时变化不可见），`scope` 声明观察范围与预算截断。用不用由你决定。
