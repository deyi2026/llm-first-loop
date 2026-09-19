---
title: 镜像 restart_mirror.sh R2 改写三连环事故：.pth 翻转违约 + resolver 空输出 + 凭证错配对——与共享 venv 协议的重申
scenario: "双区重启时镜像 restart_mirror.sh（R2 改写版）连环翻车：① WEB_PORT 解析为空串——顶部 resolver 查询不带 PYTHONPATH，共享 venv editable 或 shell 残留使其跑到主区 resolver，对镜像语义输出空且 exit 0，$(cmd || echo 8903) 只兜失败不兜空串 → \"port 无监听进程\"假停机 + 新进程绑 8903 撞未停的旧进程（Errno 48）；② all 模式先杀飞书再启 web，web 失败即中止 → 飞书桥被杀后无人拉起（心跳文件残留 connected 假象，进程实亡）；③ 修复后飞书预检 10014 app secret invalid——shell 残留主区 FEISHU_APP_ID（无配套 SECRET）+ 文件里的镜像 secret 拼成错配对（旧脚本 source .env 覆盖残留而掩盖，R2 不 source 后暴露）。另发现共享 venv 的 editable .pth 被翻指向镜像 src——违反 venv 属主区协议。"
root_cause: "R2 改写的三个假设在多实例共享 venv 环境下全部不成立：A) \"resolver 查询不需要 PYTHONPATH\"——错，共享 venv editable/shell 残留会让查询跑主区代码；B) \"$(cmd || echo fallback) 能兜底\"——错，只兜非零退出，兜不了空串成功；C) \".pth 天然指向镜像 src，服务可零 PYTHONPATH\"——错，.pth 属主区（venv 属主），被外力翻向镜像会反向毒化主区一切无显式 PYTHONPATH 的 import（测试/CLI/工具），翻向主区则镜像加载错代码——唯一稳态是协议 §3：主区持 .pth，镜像显式自带 PYTHONPATH 自卫。凭证层：环境优先语义下，残留的单边凭证键（只有 APP_ID 无 SECRET）会与文件值拼出错配对。"
solution: "修复 restart_mirror.sh 四处（全部已实证）：① resolver 查询带 PYTHONPATH=镜像 src + 空值参数展开兜底：WEB_PORT=\"$(PYTHONPATH=$MIRROR_DIR/src $VENV_PY -m llm_loop.runtime.resolver WEB_PORT 2>/dev/null || true)\"; WEB_PORT=\"${WEB_PORT:-8903}\"；② 服务启动显式注入 PYTHONPATH=$MIRROR_DIR/src（协议 §3 恢复，不依赖 .pth 指向，同时覆盖 shell 残留）；③ _prep_dsh_env 增加 unset FEISHU_APP_ID FEISHU_APP_SECRET（清凭证对残留，python 配置链从 .env/.feishu.env 读配套对）；④ .pth 翻回主区 src（printf 主区src > __editable__*.pth）。诊断工具链：空串兜底 bug 用 echo "port [$WEB_PORT]" 显形；凭证错配对用 curl POST tenant_access_token/internal 分别测文件凭证（code=0=有效）+ env | grep FEISHU 找残留 + 比对 app_id 前 10 位归属；代码身份用 ps eww 查进程 PYTHONPATH + /health 特征字段（主区有 identity 块，镜像无）。飞书被杀后心跳文件可能残留 connected——判定存活以 pgrep/lsof 为准，心跳只作辅助。"
evidence: "2026-08-29 21:45-21:53 全链实证：21:45 失败运行输出 \"port 无监听进程\"+Errno 48 撞端口，且 all 模式已静默 kill 飞书 38621（脚本无日志行）；resolver 无 PYTHONPATH 输出空/exit 0，带 PYTHONPATH=镜像 src 输出 8903；.pth 内容实测 /Users/yyj/Project/llm-first-loop-mirror/src（已翻回主区）；shell 残留 FEISHU_APP_ID=cli_a9240f（主区 app），镜像应为 cli_a92783，文件凭证直连 API code=0 有效；21:53 修复后 all 重启全绿：web 82035（PYTHONPATH=镜像src、/health 无 identity 块=镜像代码）+ 飞书 82083 心跳 connected。主区 21:44 重启的 web/feishu（76396）全程未受影响（主区脚本 L221 显式 export PYTHONPATH=本区 src，设计性自保）。"
tags: [restart_mirror, 共享venv, pth协议, resolver空输出, 凭证错配对, FEISHU残留, R2回归, 跨区污染]
source: {}
status: active
created_at: "2026-08-29T21:55:00+08:00"
updated_at: "2026-08-29T21:55:00+08:00"
---

## 重申共享 venv 协议（唯一稳态）

1. **venv 属主区**：editable .pth 永远指向主区 src。谁翻它谁制造跨区事故（两个方向都是）。
2. **镜像永远显式自带 `PYTHONPATH=$MIRROR_DIR/src`**：查询 resolver、启动服务、跑测试，一处都不能省。不依赖 .pth、不依赖"零 PYTHONPATH"设计。
3. **`$(cmd || echo fallback)` 不兜空串**：兜底一律 `${VAR:-default}` 参数展开。
4. **启动前清凭证对**：`unset FEISHU_APP_ID FEISHU_APP_SECRET`，让配置链从文件读配套对——环境优先语义下单边残留键 = 错配对工厂。
5. **服务存活判定**：pgrep/lsof 为准；心跳文件在进程被杀时可能不写终态（残留 connected 假象）。

## 给 R2 作者（镜像 AI）的回带

R2 的"配置归 python、shell 零注入"方向本身合理，但三处实现假设在共享 venv 多实例环境不成立，已按协议修复如上；`.pth 天然指向镜像 src` 的前提请从设计中删除（那是被翻过的临时状态，已翻回主区）。主区脚本因显式 PYTHONPATH（L221）幸免，但"editable .pth 已指向本区"的注释同样建立在脆弱前提上——两区都应显式、都别信 .pth。
