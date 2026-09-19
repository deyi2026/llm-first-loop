#!/usr/bin/env bash
# git_security_scan.sh —— 提交安全扫描（防 AI 自动提交误传敏感/私密/错误文件）
#
# 背景（2026-08-16）：本项目由 LLM-First Loop 自主迭代（AI 自动改代码/提交/推送），
# 无人工检查环节 → 敏感文件/本地路径/大文件必须程序化硬拦截。
#
# 两种模式：
#   --staged   pre-commit 钩子用：扫描暂存区（git diff --cached）——提交前拦截
#   --tree     CI 用：扫描整个已跟踪文件树（git ls-files）——推送后兜底
#
# 命中任一规则 → 打印命中项 + exit 1（提交/CI 失败，如实提示修复方式）。
# 规则保守防误报；确属测试夹具的可显式豁免（见 _allowlist）。

set -u
MODE="${1:---staged}"

# ── 规则 1: 禁止路径（暂存/跟踪中出现即拒；git add -f 绕过 gitignore 的兜底）──
BLOCK_PATH_PATTERNS=(
  '^data/'                # 运行时数据（会话/审计/分析结果——含私密信息，绝不入库）
  '\.env(\.[a-zA-Z0-9_-]+)?$'   # .env / .env.local / .env.bak-*
  '^\.feishu\.env$'       # 飞书密钥文件
  '\.log$'                # 运行日志（可能含任务文本/路径）
  '\.(pem|key|p12|jks|pfx)$'    # 私钥/证书
  '(^|/)\.git-credentials$'
)

# ── 规则 2: 高价值敏感内容模式（大小写不敏感；命中即拒）──
BLOCK_CONTENT_PATTERNS=(
  'BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY'   # 私钥
  'sk-[A-Za-z0-9]{16,}'                          # OpenAI 风格 API key
  'AKIA[0-9A-Z]{16}'                             # AWS access key
  'ghp_[A-Za-z0-9]{20,}'                         # GitHub PAT
  '(app_secret|api_secret|api_key|client_secret|access_token)["'"'"']?[:=]["'"'"'][A-Za-z0-9_\-]{12,}'
)

# ── 规则 3: 本地绝对路径痕迹（错误文件类：暴露本地用户名/机器路径）──
BLOCK_ABS_PATH_PATTERNS=(
  '/Users/[A-Za-z0-9_]+/'
  '/home/[A-Za-z0-9_]+/'
)

# ── 规则 4: 大文件（误提交二进制/数据导出）──
MAX_FILE_BYTES=$((1024 * 1024))  # 1MB

# ── 豁免白名单（确属测试夹具/样例，无敏感值；路径子串匹配）──
_ALLOWLIST=(
  '.env.example'                         # 公开模板（占位符，无真实值）
  'tests/unit/test_workspace_store.py'   # 编码规则测试（用样例路径验证，无真实用户）
  'tests/unit/test_history_layering.py'  # 测试数据占位符
  'tests/codearts/test_audit.py'  # 脱敏测试：夹具用 AWS 文档示例密钥验证 AK 不落日志
  'tests/unit/test_cache_block_reclassification.py'  # D-G4/G5 脱敏测试：虚构 sk- 样例验证 privacy BLOCK 保留          # 脱敏测试：夹具用 AWS 文档示例密钥验证 AK 不落日志
  'docs/local/'                          # 本地过程文档（不入库，此处兜底）
  'docs/MIRROR-workspace-protocol.md' # 镜像协议文档（合法引用工作区路径，非泄露）
    "tests/unit/test_cache_guard.py"  # 缓存守卫测试样例（sk- 模式用例）
  'tests/unit/test_r824_final_gates.py'  # R9 六门哨兵：虚构 sk- 样例验证 privacy BLOCK 保留（同 cache_block_reclassification 先例，头部自文档化）
  'skills/mirror-restart/SKILL.md'  # 镜像重启标准操作技能（命令需绝对路径，同镜像协议文档先例，非泄露）
  'tests/fixtures/wire/'  # R9 行为基线 wire fixtures：生产报文如实固化快照（报文内含工作区路径记录，非泄露；等价对照用途内容不可改写）
  'data/calib/h1c_control_bank.json'  # Gate0 项2 fixture 版本化：测试 bank 入库（PROBE 提交态自足；hash 背书于 tests/guards/fixture_manifest.json；非运行时数据，评测只读资产快照）
  'tests/fixtures/trace_leak/isomorphic-replay-pair.jsonl'  # Gate0 项2 fixture 版本化：trace 泄漏实证报文如实固化快照（内含工作区路径记录=泄漏样本本体，非泄露；同 tests/fixtures/wire/ 先例，内容不可改写）
  'tools/smx/lab/config-b.card'  # SMX lab treatment 评测卡：冻结样例，绝对路径是实验定义本体（同 tests/fixtures/wire/ 先例，内容不可改写）
  'evals/browser_smc_subject_v01/results/'  # subject_v01 measured 回执：引擎 provenance 路径记录=机器产物本体（同 tests/fixtures/wire/ 先例，回执不可改写；仅 summary.json 入库）
)

# ── 规则粒度豁免：仅跳过规则3（本地绝对路径）；规则1禁路径/规则2敏感内容/规则4大文件仍全量执行 ──
# 用于"路径痕迹是记录本体、但目录会持续新增内容"的知识档案：历史文件按原样保留，
# 新增文件仍必须过 secret/大文件安检，不能借目录逃逸（2026-09-18 审查：整目录全豁免属边界放宽）。
_ABS_PATH_ONLY_ALLOWLIST=(
  'experiences/'  # 经验档案：文档如实记录本机工作区路径=记录本体，非泄露；secret/大文件/禁路径检查不豁免
)

# ── 规则粒度豁免：仅跳过规则1（禁路径）；规则2敏感内容/规则3绝对路径/规则4大文件仍全量执行 ──
# 用于"路径前缀属历史禁区、但内容已定性为知识资产"的目录（复刻 _ABS_PATH_ONLY_ALLOWLIST 粒度模式，
# 2026-09-18 审查精神：不整目录全豁免；2026-09-20 首例 data/methods——.gitignore 09-18 已声明
# !data/methods/ 入库保全，270 文件内容全检通过后登记；后续新增文件仍过全部内容安检）
_PATH_ONLY_ALLOWLIST=(
  'data/methods/'  # 学习方法资产（METHOD.md 方法卡 + qualification.jsonl；embeddings-*.json 由 gitignore 排除）
)

# macOS/Linux 兼容的 stat 大小
_file_size() {
  if [[ "$(uname)" == "Darwin" ]]; then
    stat -f %z "$1" 2>/dev/null || echo 0
  else
    stat -c %s "$1" 2>/dev/null || echo 0
  fi
}

_is_allowed() {
  local path="$1"
  for a in "${_ALLOWLIST[@]}"; do
    [[ "$path" == *"$a"* ]] && return 0
  done
  return 1
}

# 规则粒度豁免：仅豁免"本地绝对路径"检查（experiences/ 等知识档案目录）
_abs_path_only_allowed() {
  local path="$1"
  for a in "${_ABS_PATH_ONLY_ALLOWLIST[@]}"; do
    [[ "$path" == *"$a"* ]] && return 0
  done
  return 1
}

# 规则粒度豁免：仅豁免"禁路径"检查（data/methods/ 等知识资产目录；内容/大文件/绝对路径检查不豁免）
_path_only_allowed() {
  local path="$1"
  for a in "${_PATH_ONLY_ALLOWLIST[@]}"; do
    [[ "$path" == *"$a"* ]] && return 0
  done
  return 1
}

_fail() {
  echo "❌ [git_security_scan] 命中安全规则（提交被拦截）: $1"
  echo "   文件: $2"
  echo "   修复: 移除该文件/内容后重试；确属测试样例需豁免时在脚本 _ALLOWLIST 显式登记。"
  exit 1
}

main() {
  local files=() f_line
  if [[ "$MODE" == "--staged" ]]; then
    while IFS= read -r f_line; do files+=("$f_line"); done \
      < <(git diff --cached --name-only --diff-filter=ACM 2>/dev/null)
  else
    while IFS= read -r f_line; do files+=("$f_line"); done < <(git ls-files 2>/dev/null)
  fi
  [[ ${#files[@]} -eq 0 ]] && exit 0

  local f blob content size
  for f in "${files[@]}"; do
    _is_allowed "$f" && continue

    # 规则 1: 路径（_PATH_ONLY_ALLOWLIST 仅豁免本规则；规则2/3/4 仍全量执行）
    _path_only_allowed "$f" || for pat in "${BLOCK_PATH_PATTERNS[@]}"; do
      [[ "$f" =~ $pat ]] && _fail "禁止路径匹配 [$pat]" "$f"
    done

    # 规则 4: 大文件（工作区文件）
    [[ -f "$f" ]] || continue
    size="$(_file_size "$f")"
    (( size > MAX_FILE_BYTES )) && _fail "文件过大 (${size}B > 1MB)" "$f"

    # 规则 2/3: 内容扫描（staged 用索引 blob，tree 用工作区文件；跳过二进制）
    if [[ "$MODE" == "--staged" ]]; then
      blob="$(git show ":$f" 2>/dev/null || cat "$f")"
    else
      blob="$(cat "$f" 2>/dev/null)"
    fi
    [[ -z "$blob" ]] && continue
    if ! LC_ALL=C grep -qI . <<<"$blob"; then
      continue  # 二进制
    fi
    for pat in "${BLOCK_CONTENT_PATTERNS[@]}"; do
      if LC_ALL=C grep -qiE "$pat" <<<"$blob"; then
        _fail "敏感内容匹配 [$pat]" "$f"
      fi
    done
    for pat in "${BLOCK_ABS_PATH_PATTERNS[@]}"; do
      _abs_path_only_allowed "$f" && break  # 仅此规则豁免知识档案目录；secret/大文件/禁路径不豁免
      if LC_ALL=C grep -qE "$pat" <<<"$blob"; then
        _fail "本地绝对路径匹配 [$pat]" "$f"
      fi
    done
  done
  echo "✅ [git_security_scan] 通过（${#files[@]} 个文件无敏感/错误内容）"
  exit 0
}

main
