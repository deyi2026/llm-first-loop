---
title: write_scope：deny 模式下用裸目录名声明排除集是静默 fail-open（allow 下则是 fail-closed 空授权）
scenario: "给子代理或会话声明写域排除集时，用最自然的写法 {\"paths\": [\"src\"], \"mode\": \"deny\"} 意图\"禁止写 src 目录\"，实际 parse 接受（declared=True）但排除集不匹配 src 下任何文件，src/ 下全部可写，且无任何报错或告警。镜像情形：allow 模式下写 {\"paths\": [\"docs\"]} 意图\"允许写 docs 目录\"，实际对 docs 下任何文件都返回 not_in_allow_list，子代理写入被拒且回执只有 not_in_allow_list，不指向 pattern 语义这一根因。"
root_cause: "paths 用 fnmatch 语义匹配相对路径：'src' 只能匹配相对路径恰好等于 'src' 的条目，而任何文件的相对路径都是 'src/xxx/yyy.py'，永远不等于 'src'。因此无通配符的目录名条目在 allow 下匹配零路径（fail-closed，安全但授权无效），在 deny 下也匹配零路径（fail-open，排除无效=等于没禁）。parse_write_scope 的 _deny_entry_viable 只拦截\"归一后为空\"的空转条目（如 './'、空段），未覆盖\"归一后非空但永不匹配任何子路径\"的目录名形态，因此该形态被接受为 declared=True，使用者无法从回执看出排除集实际为空。"
solution: "1) 当下用法：目录必须写成 dir/**（覆盖子树）或 dir/*（仅一层），永不用裸目录名。2) 判定口诀：allow 模式下裸目录名=授零权（fail-closed，摩擦）；deny 模式下裸目录名=排零项（fail-open，安全回退）。3) 若需在代码层修复：在 parse_write_scope 的 deny 分支增加\"条目能否匹配至少一类路径\"的可判定检查（或对无通配的目录名自动补 /**），并让 allow 回执的 reason 区分\"pattern 不匹配任何路径\"与\"路径在 allow 列表外\"。4) 复核手段：声明后先跑 scope_allows 打样一个目标文件，确认 allowed 与预期一致，再交给执行方。"
evidence: "实测命令：.venv/bin/python -c \"from llm_loop.core.write_scope import parse_write_scope, scope_allows; s=parse_write_scope({'paths':['src'],'mode':'deny'}); print(scope_allows(s, '<root>/src/llm_loop/tools/sandbox.py', '<root>'))\" → 输出 (True, '')。对照：deny ['docs/*'] 与 deny ['docs/**'] 对 docs 下文件均返回 (False, 'denied_by_deny_list')；allow ['docs'] 对 docs 下文件返回 (False, 'not_in_allow_list')，allow ['docs/*'] 返回 (True, '')。由父代理在 2026-10-31 于主仓库 HEAD 55b53ab 执行。"
tags: [write_scope, fnmatch, fail-open, 安全回退, 子代理编排, deny模式]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T14:06:19.668533+08:00"
updated_at: "2026-10-31T14:06:19.668533+08:00"
---