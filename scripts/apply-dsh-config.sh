#!/usr/bin/env bash
# apply-dsh-config.sh — 修复 DSH 客户端 deepseek key 无效 + 追加 GLM-5.3 备用 provider
#
# 副作用边界: 本脚本只写 ~/.dsh/{.credentials,settings}.yaml，
#   不动镜像 .env、不动任何配置文件。备份 + 原子写，幂等可重跑。
#
# 用法: bash scripts/apply-dsh-config.sh
#       DSH_DIR=/path/to/dsh bash scripts/apply-dsh-config.sh
#       PYTHON=/usr/bin/python3 bash scripts/apply-dsh-config.sh
#       DRY_RUN=1 bash scripts/apply-dsh-config.sh  # 只检查，不写
#
# 退出码: 0=全部成功；1=前置检查失败；2=写失败（ACL 锁）+ fallback 指引已输出

set -uo pipefail

# ── 配置（可被 env 覆盖）──
DSH="${DSH_DIR:-$HOME/.dsh}"
MIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$MIR/.venv/bin/python}"
TS="$(date +%Y%m%d-%H%M%S)"
DRY_RUN="${DRY_RUN:-0}"

CRED="$DSH/.credentials.yaml"
SETT="$DSH/settings.yaml"

# ── 前置检查（fail-fast）──
err=0
[[ -d "$DSH" ]]           || { echo "[FAIL] DSH 目录不存在: $DSH（设 DSH_DIR 或确认 ~/.dsh）" >&2; err=1; }
[[ -f "$CRED" ]]          || { echo "[FAIL] $CRED 不存在" >&2; err=1; }
[[ -f "$SETT" ]]          || { echo "[FAIL] $SETT 不存在" >&2; err=1; }
[[ -x "$PY" ]]            || { echo "[FAIL] python 不可不可: $PY（设 PYTHON 覆盖）" >&2; err=1; }
(( err == 0 )) || exit 1

# ── 提取镜像 .env 的 key（保留行内注释剥离）──
_read_kv() {
  local key="$1" file="$2"
  grep -m1 "^${key}=" "$file" | cut -d= -f2- | sed 's/[[:space:]]*#.*//' | tr -d ' '
}
DEEPSEEK_KEY="$(_read_kv DEEPSEEK_API_KEY "$MIR/.env")"
GLM_KEY="$(_read_kv GLM_API_KEY "$MIR/.env")"

[[ -n "$DEEPSEEK_KEY" ]] || { echo "[FAIL] 镜像 .env 缺 DEEPSEEK_API_KEY" >&2; exit 1; }
[[ -n "$GLM_KEY" ]]      || { echo "[FAIL] 镜像 .env 缺 GLM_API_KEY"      >&2; exit 1; }

# 模糊化（用于 echo，避免明文）
_mask() { local k="$1"; echo "${k:0:6}…${k: -4} (len=${#k})"; }

# ── 报告（key 只显示长度+前后几位）──
echo "── apply-dsh-config ──"
echo "DSH:               $DSH"
echo "MIR (镜像):         $MIR"
echo "DSH deepseek key:  $(_mask "$DEEPSEEK_KEY")"
echo "DSH GLM key:       $(_mask "$GLM_KEY")"
echo "DRY_RUN:           $DRY_RUN"
echo

# ── 备份（备份失败 abort——写无回滚太危险）──
[[ "$DRY_RUN" == "1" ]] || {
  cp "$CRED" "$CRED.bak-$TS-glm-fix"  || { echo "[FAIL] 备份 $CRED 失败，放弃写" >&2; exit 1; }
  cp "$SETT" "$SETT.bak-$TS-add-glm"  || { echo "[FAIL] 备份 $SETT 失败，放弃写" >&2; exit 1; }
  echo "[OK] 备份: $CRED.bak-$TS-glm-fix"
  echo "[OK] 备份: $SETT.bak-$TS-add-glm"
}

# ── 改 .credentials.yaml（幂等：key 存在则替换，不存在则追加）──
echo
echo "── 改 .credentials.yaml ──"
CRED_OUT=$("$PY" - "$CRED" "$DEEPSEEK_KEY" "$GLM_KEY" "$DRY_RUN" << 'PYEOF'
import sys, pathlib
cred_path, deepseek_key, glm_key, dry = sys.argv[1:5]
p = pathlib.Path(cred_path)
text = p.read_text()
new_text = text

# DEEPSEEK_API_KEY: 替换（不存在则不动？必然存在因前置已验证）
import re
def replace_kv(name, value, text):
    # 匹配 "  NAME: ..."（前导2空格 = refs 子层）
    pat = re.compile(rf'^(  {re.escape(name)}:\s*)(.+?)$', re.MULTILINE)
    m = pat.search(text)
    if m:
        return pat.sub(rf'\g<1>{value}', text, count=1), 'replaced'
    return text, 'not_found'

new_text, d_action = replace_kv('DEEPSEEK_API_KEY', deepseek_key, new_text)
new_text, g_action = replace_kv('GLM_API_KEY',      glm_key,      new_text)

if d_action == 'replaced' and new_text != text:
    if dry != '1':
        p.write_text(new_text)
    print(f'[OK] DEEPSEEK_API_KEY: {d_action}')
    print(f'[OK] GLM_API_KEY:      {g_action}')
elif d_action == 'not_found':
    print(f'[FAIL] DEEPSEEK_API_KEY 行未找到（文件结构可能与预期不符）', file=sys.stderr)
    sys.exit(1)
else:
    print(f'[SKIP] 无需修改')
PYEOF
)
CRED_RC=$?
echo "$CRED_OUT"
(( CRED_RC == 0 )) || { CRED_OK=0; echo "[FAIL] .credentials.yaml 写失败"; }

# ── 改 settings.yaml（幂等：glm-coding 存在则替换，不存在则在 lmstudio 后插入）──
echo
echo "── 改 settings.yaml ──"
SETT_OUT=$("$PY" - "$SETT" "$DRY_RUN" << 'PYEOF'
import sys, pathlib, re
sett_path, dry = sys.argv[1], sys.argv[2]
p = pathlib.Path(sett_path)
text = p.read_text()

# glm-coding 块（统一字面量，便于检测"已存在"）
glm_block = (
    '      glm-coding:\n'
    '        {\n'
    '          displayName: 智谱 GLM Coding Plan,\n'
    '          api: openai-completions,\n'
    '          baseURL: https://open.bigmodel.cn/api/coding/paas/v4,\n'
    '          apiKeyEnv: GLM_API_KEY,\n'
    '          models:\n'
    '            [\n'
    '              {\n'
    '                  id: glm-5.3,\n'
    '                  name: GLM-5.3,\n'
    '                  contextWindow: 1000000,\n'
    '                  maxTokens: 16384\n'
    '                }\n'
    '            ]\n'
    '        }\n'
)

# 检测 glm-coding 已存在（按"      glm-coding:" 标识）
marker = '      glm-coding:'
new_text = text
action = 'inserted'

if marker in text:
    # 替换：删旧 glm-coding 块（含其后第一个顶层 '    }'），插新块
    # 旧块以 "      glm-coding:" 开头，其后是 14 行（model 列表），闭合于 "        }"
    # 用正则非贪婪匹配整个块（含换行）
    pat = re.compile(
        rf'^{re.escape(marker)}.*?(?=\n    \}}\n)',
        re.MULTILINE | re.DOTALL,
    )
    new_text, n = pat.subn(glm_block, text, count=1)
    if n:
        action = 'replaced'
    else:
        action = 'pattern_missed'
else:
    # 插入位置: 找 "lmstudio 块结束的 '}'" 后面、"providers 块结束的 '    }'" 前面
    # lmstudio 块以 8 空格缩进的 '}' 闭合（lmstudio 内部字段）
    # providers 块以 4 空格缩进的 '}' 闭合
    # 模式: 8 空格 '}' 后跟 \n '    }'
    pat = re.compile(
        r'^(        \})\n(    \}\n)',
        re.MULTILINE,
    )
    new_text, n = pat.subn(r'\1\n' + glm_block + r'\2', text, count=1)
    if not n:
        action = 'pattern_missed'

if action == 'pattern_missed':
    print(f'[FAIL] 找不到 lmstudio/provides 闭合位置（文件结构已变）', file=sys.stderr)
    sys.exit(1)

if dry != '1' and new_text != text:
    p.write_text(new_text)
print(f'[OK] glm-coding: {action}')
PYEOF
)
SETT_RC=$?
echo "$SETT_OUT"
(( SETT_RC == 0 )) || echo "[FAIL] settings.yaml 写失败"

# ── 总结 + 失败时输出手动指引（绝不 echo 明文 key）──
echo
if [[ $CRED_RC -eq 0 && $SETT_RC -eq 0 ]]; then
  echo "============================================================"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DONE] DRY_RUN=1 — 未实际写入。请去掉 DRY_RUN 重跑。"
  else
    echo "[DONE] 两个文件都已更新。重启 DSH 客户端让新配置生效。"
  fi
  echo "============================================================"
  exit 0
fi

echo "============================================================"
echo "手动指引（脚本写失败——多半是 DSH 进程给文件加了 ACL 锁）"
echo "============================================================"
echo
echo "请用 TextEdit/vim 打开下面两个文件手动改："
echo
echo "① $CRED"
echo "   - 第 3 行 DEEPSEEK_API_KEY: <旧值>  整行替换为："
echo "     DEEPSEEK_API_KEY: <新值>"
echo "     <新值取自镜像 .env 第 N 行的值: grep ^DEEPSEEK_API_KEY= $MIR/.env>"
echo "   - 如已存在 GLM_API_KEY: <值> 行，替换；否则在 KIMI 行后追加 GLM_API_KEY 行"
echo "     （值同样 grep ^GLM_API_KEY= $MIR/.env）"
echo
echo "② $SETT"
echo "   - 在 llm-pi-ai.providers 块的 lmstudio 关闭 '}' 之后插入 glm-coding 段："
echo "     （脚本输出已给出完整块，本指引不 echo 明文以免泄露）"
echo "   - 如已有 glm-coding 段则替换"
echo
echo "改完后重启 DSH 客户端让新配置生效。"
echo "DSH UI 切默认模型：provider 选 glm-coding → model 选 GLM-5.3 启用 GLM 备用。"
exit 2