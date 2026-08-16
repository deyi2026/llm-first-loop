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
  'docs/local/'                          # 本地过程文档（不入库，此处兜底）
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

    # 规则 1: 路径
    for pat in "${BLOCK_PATH_PATTERNS[@]}"; do
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
      if LC_ALL=C grep -qE "$pat" <<<"$blob"; then
        _fail "本地绝对路径匹配 [$pat]" "$f"
      fi
    done
  done
  echo "✅ [git_security_scan] 通过（${#files[@]} 个文件无敏感/错误内容）"
  exit 0
}

main
