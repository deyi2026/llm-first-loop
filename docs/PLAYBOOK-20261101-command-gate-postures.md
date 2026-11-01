# PLAYBOOK：命令闸与一次性脚本的推荐姿势（2026-11-01）

> 目的：把「哪些写法会被硬阻断、应该怎么写」写成可复制姿势，减少每次试探一轮交互的成本。
> 边界：本文只解释现状，**不放宽任何授权**；护栏强度由 `src/llm_loop/tools/safety.py` 决定。

## 1. 会被硬阻断（E6_CATASTROPHIC_HARD）的两种形态

| 形态 | 规则标签 | 代码位置 |
|---|---|---|
| here-doc 直接喂解释器（`python3 <<EOF … EOF`） | `here-doc 交给解释器执行` | `safety.py` `_CATASTROPHIC_PATTERNS` |
| 管道直连解释器（`echo x \| python3 -`、`… \| sh`） | `任意管道直连解释器执行` | 同上 |

实测回执（本会话 2026-11-01，均为真实硬阻断回执）：

- 17:00:34 写探针脚本时正文里出现管道连解释器字样 → `[安全硬阻断][E6_CATASTROPHIC_HARD] … 任意管道直连解释器执行`；
- 17:00:11 here-doc 喂解释器形态 → `[安全硬阻断] … here-doc 交给解释器执行`；
- 17:07:xx 用 printf 写本文件（正文含上述反例）再次被拦 → 改用 `edit_file` 落盘后成功。

## 2. 数据不是命令（2026-11-01 修正，EVO-20261101-366cf6cd）

引号内字面量与 **quoted-delimiter** here-doc 正文属于数据，不参与「谁在执行」这类结构规则判定：

- `printf '%s' 'echo x | python3 -' > /tmp/note.md` 只是写一行示例文本，**不再**被当成管道执行；
- `cat > docs/note.md <<'EOF' … EOF` 正文里出现 `grep`/`cat`/`git status` 字样也不再触发；
- 引号**不配对**时无法静态判定 → fail-closed 拒绝，并在 evidence 里给 `reason_code=unverifiable_quoted_data`（不冒充「真命中」）；
- 解释器载荷（`bash -c "…"`、`sh -c "…"`）仍由分词层递归重扫，未放宽。

适用条件：运行中的服务进程若仍是旧代代码，上述修正不会立即生效——`service_control publish + restart` 之后才是新判定。

## 3. 推荐姿势（实测可用）

一次性脚本一律「先落盘、再执行」：

```bash
printf '%s\n' \
  'import sys' \
  'print(sys.version)' \
  > /tmp/lfl_probe.py && python3 /tmp/lfl_probe.py
```

- 多行 shell 同理：写 `.sh` 文件再 `bash file.sh`；
- 要改工作区文件时优先 `edit_file`（带快照校验）或 `printf … > file`，不要用 here-doc 拼文件正文。

## 4. 反例

```bash
python3 <<EOF          # 硬阻断：here-doc 交给解释器
print(1)
EOF

echo print(1) | python3 -   # 硬阻断：管道直连解释器
```

## 5. 确需被拦操作时

走既有提权通道，不动护栏、不换说法重试：`escalation_request`（同一命令 + 理由）→ web 面板人工审批 → 凭一次性 `escalation_token` 重发同一命令。审批回执是唯一放行依据。

## 6. 成本观测（本轮）

本会话因该形态损失 3 轮交互（2 次硬阻断 + 1 次改写探针）。按本文姿势可降为 0。
